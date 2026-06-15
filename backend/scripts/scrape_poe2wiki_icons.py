"""Batch-download PoE2 entity icons from poe2wiki.net via MediaWiki API.

Discovers pages under game categories (ascendancies, gems, uniques, passives),
selects the best primary icon per page, downloads PNG/WebP/JPG, and writes manifests.

Usage (from repo root or backend/):
  python backend/scripts/scrape_poe2wiki_icons.py
  python backend/scripts/scrape_poe2wiki_icons.py --limit 30
  python backend/scripts/scrape_poe2wiki_icons.py --skip-download
  python backend/scripts/scrape_poe2wiki_icons.py --download-all-images

Outputs under backend/data/:
  icons/wiki/{entity_type}/{slug}.{ext}     primary icon files
  icons/wiki/_all/{page_slug}/{filename}    optional: every non-junk image on page
  wiki_icons/manifest.jsonl                 one row per wiki page (primary icon)
  wiki_icons/all_images.jsonl               one row per (page, image file)
  wiki_icons/index.json                     flat lookup keys → local path + url
  wiki_icons/stats.json                     run summary
  wiki_icons/failures.jsonl                 pages/images that failed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent


def resolve_data_dir(override: str | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("POE2LI_DATA_DIR")
    if env:
        return Path(env)
    repo_data = REPO_ROOT / "data"
    if repo_data.is_dir():
        return repo_data
    return ROOT / "data"


DATA_DIR = resolve_data_dir()
ICONS_DIR = DATA_DIR / "icons" / "wiki"
WIKI_META_DIR = DATA_DIR / "wiki_icons"

WIKI_API = "https://www.poe2wiki.net/api.php"
HEADERS = {
    "User-Agent": (
        "PoE2LI-WikiIconScraper/1.0 "
        "(offline batch; +https://github.com/TangCuPaiGu233/PoE2LI)"
    ),
}

# Root categories — subcategories are walked recursively (ns=14).
SEED_CATEGORIES: list[tuple[str, str]] = [
    ("Category:Ascendancy_classes", "ascendancy"),
    ("Category:Ascendancy_notable_passive_skills", "asc_notable"),
    ("Category:Ascendancy_minor_passive_skills", "asc_minor"),
    ("Category:Ascendancy_basic_passive_skills", "asc_basic"),
    ("Category:Skill_gems", "skill"),
    ("Category:Support_gems", "support"),
    ("Category:Spirit_gems", "spirit"),
    ("Category:Meta_skill_gems", "meta_skill"),
    ("Category:Lineage_support_gems", "lineage_support"),
    ("Category:Unique_items", "item"),
    ("Category:Keystone_passive_skills", "keystone"),
    ("Category:Notable_passive_skills", "notable"),
    ("Category:Character_classes", "class"),
    ("Category:Jewels", "jewel"),
    ("Category:Flasks", "flask"),
    ("Category:Waystones", "waystone"),
    ("Category:Omens", "omen"),
    ("Category:Charms", "charm"),
    ("Category:Currency", "currency"),
]

SKIP_PAGE_RE = re.compile(
    r"^(List of |Timeline of |Unique item$|Demigod unique$|Lineage support gem$)",
    re.I,
)

IMAGE_DENY_EXACT = frozenset(
    {
        "questionmark.png",
        "help.svg",
        "placeholder_character_portrait.png",
        "placeholder_character_class.png",
        "level_up_icon_small.png",
        "dexterityicon_small.png",
        "strengthicon_small.png",
        "intelligenceicon_small.png",
    },
)

IMAGE_DENY_SUBSTR = (
    "_small.png",
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("wiki_icons")


def wiki_page_slug(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_") or "unknown"


def wiki_file_prefix(title: str) -> str:
    """Wiki filenames use underscores; apostrophes kept."""
    return title.replace(" ", "_")


def normalize_fname(name: str) -> str:
    return name.replace(" ", "_").lower()


def wiki_direct_image_url(filename: str) -> str:
    """MediaWiki upload path from filename (fallback when imageinfo missing)."""
    key = filename.replace(" ", "_")
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    encoded = urllib.parse.quote(key)
    return f"https://www.poe2wiki.net/images/{digest[0]}/{digest[0:2]}/{encoded}"


def should_deny_image(filename: str, *, page_title: str, entity_type: str) -> bool:
    low = normalize_fname(filename)
    if low in IMAGE_DENY_EXACT:
        return True
    if low.endswith(".svg"):
        return True
    for sub in IMAGE_DENY_SUBSTR:
        if sub in low:
            return True
    if entity_type != "item" and low.endswith("3d.png"):
        return True
    # Navbox portraits on ascendancy pages: drop other classes' portraits
    if entity_type == "ascendancy" and low.endswith("_portrait.png"):
        prefix = wiki_file_prefix(page_title).lower()
        if prefix not in low:
            return True
    if entity_type == "ascendancy" and "character_class" in low:
        prefix = wiki_file_prefix(page_title).lower()
        if prefix not in low:
            return True
    return False


def filter_images(
    filenames: list[str],
    *,
    page_title: str,
    entity_type: str,
) -> list[str]:
    out: list[str] = []
    for name in filenames:
        if should_deny_image(name, page_title=page_title, entity_type=entity_type):
            continue
        out.append(name)
    return out


def pick_primary_icon(
    page_title: str,
    entity_type: str,
    images: list[str],
) -> tuple[str | None, str]:
    """Return (filename, reason)."""
    filtered = filter_images(images, page_title=page_title, entity_type=entity_type)
    if not filtered:
        return None, "no_images_after_filter"

    prefix = wiki_file_prefix(page_title)
    prefix_low = prefix.lower()

    def norm(name: str) -> str:
        return normalize_fname(name)

    def has_prefix(name: str) -> bool:
        nlow = norm(name)
        return nlow.startswith(prefix_low) or prefix_low in nlow

    def first_match(pred) -> str | None:
        for name in filtered:
            if pred(name):
                return name
        return None

    if entity_type == "ascendancy":
        hit = first_match(lambda n: norm(n) == f"{prefix_low}_portrait.png")
        if hit:
            return hit, "ascendancy_portrait"
        hit = first_match(lambda n: norm(n).endswith("_ascendancy_class.png"))
        if hit:
            return hit, "ascendancy_class"
        hit = first_match(lambda n: "official_art" in norm(n))
        if hit:
            return hit, "official_art"
        return None, "no_ascendancy_match"

    if entity_type in ("skill", "support", "spirit", "meta_skill", "lineage_support"):
        for suffix in ("_skill_icon.png", "_inventory_icon.png"):
            hit = first_match(lambda n, s=suffix: has_prefix(n) and norm(n).endswith(s))
            if hit:
                return hit, suffix.strip("_.").replace("_", "")
        hit = first_match(lambda n: has_prefix(n) and "skill_icon" in norm(n))
        if hit:
            return hit, "skill_icon_fuzzy"
        hit = first_match(lambda n: has_prefix(n) and "inventory_icon" in norm(n))
        if hit:
            return hit, "inventory_icon_fuzzy"

        gem_icons = [
            n
            for n in filtered
            if "inventory_icon" in norm(n) or "skill_icon" in norm(n)
        ]
        if len(gem_icons) == 1:
            return gem_icons[0], "single_gem_icon"
        inv_only = [n for n in gem_icons if "inventory_icon" in norm(n)]
        if len(inv_only) == 1:
            return inv_only[0], "only_inventory_icon"
        skill_only = [n for n in gem_icons if "skill_icon" in norm(n)]
        if len(skill_only) == 1:
            return skill_only[0], "only_skill_icon"

        title_tokens = {t for t in re.findall(r"[a-z0-9]+", prefix_low) if len(t) > 2}
        if title_tokens and gem_icons:
            best: str | None = None
            best_score = 0
            for name in gem_icons:
                fn_tokens = set(re.findall(r"[a-z0-9]+", norm(name)))
                score = len(title_tokens & fn_tokens)
                if score > best_score:
                    best_score = score
                    best = name
            if best and best_score >= 2:
                return best, "gem_token_overlap"

        return None, "no_gem_match"

    if entity_type == "item":
        hit = first_match(lambda n: has_prefix(n) and "inventory_icon" in norm(n))
        if hit:
            return hit, "unique_inventory"
        inv = [n for n in filtered if "inventory_icon" in norm(n)]
        if len(inv) == 1:
            return inv[0], "single_inventory"
        if inv:
            return inv[0], "first_inventory_fallback"
        hit = first_match(
            lambda n: has_prefix(n) and "3d" not in norm(n) and norm(n).endswith(".png"),
        )
        if hit:
            return hit, "unique_png"
        return None, "no_item_match"

    if entity_type in ("jewel", "flask", "waystone", "omen", "charm", "currency"):
        hit = first_match(lambda n: has_prefix(n) and "inventory_icon" in norm(n))
        if hit:
            return hit, "inventory_icon"
        hit = first_match(lambda n: has_prefix(n) and norm(n).endswith(".png"))
        if hit:
            return hit, "png_prefix"
        return None, "no_misc_item_match"

    if entity_type in (
        "asc_notable",
        "asc_minor",
        "asc_basic",
        "keystone",
        "notable",
    ):
        hit = first_match(lambda n: has_prefix(n) and "passive_skill_icon" in norm(n))
        if hit:
            return hit, "passive_skill_icon_prefix"
        hit = first_match(lambda n: "passive_skill_icon" in norm(n))
        if hit:
            return hit, "passive_skill_icon"
        return None, "no_passive_icon"

    if entity_type == "class":
        hit = first_match(lambda n: norm(n).endswith("_portrait.png"))
        if hit:
            return hit, "class_portrait"
        hit = first_match(lambda n: "character_class" in norm(n))
        if hit:
            return hit, "character_class"
        return None, "no_class_match"

    hit = first_match(lambda n: has_prefix(n))
    if hit:
        return hit, "prefix_fallback"
    if len(filtered) == 1:
        return filtered[0], "single_image"
    return None, "ambiguous"


@dataclass
class PageJob:
    title: str
    entity_type: str
    source_category: str


@dataclass
class PageResult:
    title: str
    entity_type: str
    source_category: str
    wiki_url: str
    all_images: list[str] = field(default_factory=list)
    filtered_images: list[str] = field(default_factory=list)
    primary_image: str | None = None
    pick_reason: str = ""
    image_url: str | None = None
    local_path: str | None = None
    status: str = "pending"
    error: str | None = None


class WikiClient:
    def __init__(self, delay: float = 0.35) -> None:
        self.session = requests.Session()
        self.session.trust_env = False  # ignore broken system HTTP(S)_PROXY
        self.session.proxies = {"http": None, "https": None}
        self.session.headers.update(HEADERS)
        self.delay = delay
        self._last = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last = time.monotonic()

    def api(self, **params: object) -> dict:
        params.setdefault("format", "json")
        last_exc: Exception | None = None
        for attempt in range(8):
            self._throttle()
            try:
                r = self.session.get(WIKI_API, params=params, timeout=45)
                if r.status_code == 429:
                    wait = float(r.headers.get("Retry-After", min(60, 2 ** attempt)))
                    logger.warning("429 rate limit — sleeping %.1fs (attempt %d)", wait, attempt + 1)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    raise RuntimeError(data["error"])
                return data
            except (requests.RequestException, RuntimeError) as exc:
                last_exc = exc
                if attempt < 7:
                    time.sleep(min(30, 2 ** attempt))
                    continue
                raise
        raise RuntimeError(f"wiki api failed after retries: {last_exc}")

    def category_members(
        self,
        category: str,
        *,
        cmtype: str | None = None,
    ) -> list[dict]:
        members: list[dict] = []
        cont: dict | None = {}
        while cont is not None:
            params: dict = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": category,
                "cmlimit": "500",
            }
            if cmtype:
                params["cmtype"] = cmtype
            if cont:
                params.update(cont)
            data = self.api(**params)
            members.extend(data.get("query", {}).get("categorymembers", []))
            cont = data.get("continue")
        return members

    def pages_images(self, titles: list[str]) -> dict[str, list[str]]:
        """Batch-fetch image filenames for wiki pages."""
        out: dict[str, list[str]] = {}
        for i in range(0, len(titles), 50):
            batch = titles[i : i + 50]
            data = self.api(
                action="query",
                titles="|".join(batch),
                prop="images",
                imlimit="500",
            )
            for _pid, page in data.get("query", {}).get("pages", {}).items():
                if int(_pid) < 0:
                    continue
                title = page.get("title", "")
                imgs = [x["title"].removeprefix("File:") for x in page.get("images", [])]
                out[title] = imgs
        return out

    def file_urls(self, filenames: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        unique = list(dict.fromkeys(filenames))
        for i in range(0, len(unique), 50):
            batch = unique[i : i + 50]
            titles = "|".join(f"File:{f}" for f in batch)
            data = self.api(
                action="query",
                titles=titles,
                prop="imageinfo",
                iiprop="url",
            )
            for _pid, page in data.get("query", {}).get("pages", {}).items():
                if int(_pid) < 0:
                    continue
                fname = page.get("title", "").removeprefix("File:")
                info = (page.get("imageinfo") or [{}])[0]
                url = info.get("url")
                if fname and url:
                    out[fname] = url
                    out[normalize_fname(fname)] = url
        missing = [f for f in unique if f not in out and normalize_fname(f) not in out]
        for fname in missing:
            data = self.api(
                action="query",
                titles=f"File:{fname}",
                prop="imageinfo",
                iiprop="url",
            )
            for _pid, page in data.get("query", {}).get("pages", {}).items():
                if int(_pid) < 0:
                    continue
                resolved = page.get("title", "").removeprefix("File:")
                info = (page.get("imageinfo") or [{}])[0]
                url = info.get("url")
                if resolved and url:
                    out[fname] = url
                    out[resolved] = url
                    out[normalize_fname(resolved)] = url
        return out

    def resolve_file_url(self, filename: str, url_map: dict[str, str]) -> str | None:
        if filename in url_map:
            return url_map[filename]
        nf = normalize_fname(filename)
        if nf in url_map:
            return url_map[nf]
        for key, url in url_map.items():
            if normalize_fname(key) == nf:
                return url
        direct = wiki_direct_image_url(filename)
        self._throttle()
        try:
            r = self.session.head(direct, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return direct
        except requests.RequestException:
            pass
        return None

    def download(self, url: str, dest: Path) -> None:
        last_exc: Exception | None = None
        for attempt in range(6):
            self._throttle()
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                r = self.session.get(url, timeout=60)
                if r.status_code == 429:
                    wait = float(r.headers.get("Retry-After", min(60, 2 ** attempt)))
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                dest.write_bytes(r.content)
                return
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < 5:
                    time.sleep(min(15, 2 ** attempt))
                    continue
                raise
        raise RuntimeError(f"download failed: {last_exc}")


def collect_pages(
    client: WikiClient,
    *,
    cache_path: Path | None = None,
    use_cache: bool = True,
) -> list[PageJob]:
    if use_cache and cache_path and cache_path.is_file():
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        jobs = [PageJob(**row) for row in raw]
        logger.info("Loaded %d pages from cache %s", len(jobs), cache_path)
        return jobs

    jobs: list[PageJob] = []
    seen_pages: set[str] = set()

    for root_cat, default_type in SEED_CATEGORIES:
        queue: list[tuple[str, str]] = [(root_cat, default_type)]
        visited_cats: set[str] = set()

        while queue:
            cat, etype = queue.pop(0)
            if cat in visited_cats:
                continue
            visited_cats.add(cat)

            for m in client.category_members(cat, cmtype="subcat"):
                queue.append((m["title"], etype))

            for m in client.category_members(cat, cmtype="page"):
                title = m["title"]
                if SKIP_PAGE_RE.match(title):
                    continue
                if title in seen_pages:
                    continue
                seen_pages.add(title)
                jobs.append(PageJob(title=title, entity_type=etype, source_category=cat))

        logger.info("category tree %s → %d pages so far", root_cat, len(jobs))

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps([job.__dict__ for job in jobs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Wrote page cache → %s", cache_path)

    return jobs


def find_existing_icon(entity_type: str, title: str) -> Path | None:
    slug = wiki_page_slug(title)
    folder = ICONS_DIR / entity_type
    if not folder.is_dir():
        return None
    matches = sorted(folder.glob(f"{slug}.*"))
    return matches[0] if matches else None


def page_result_from_row(row: dict) -> PageResult:
    return PageResult(
        title=row["title"],
        entity_type=row["entity_type"],
        source_category=row.get("source_category", ""),
        wiki_url=row.get("wiki_url", ""),
        primary_image=row.get("primary_image"),
        pick_reason=row.get("pick_reason", ""),
        image_url=row.get("image_url"),
        local_path=row.get("local_path"),
        status=row.get("status", ""),
        error=row.get("error", ""),
    )


def load_manifest_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def page_result_row(pr: PageResult) -> dict:
    return {
        "title": pr.title,
        "title_slug": wiki_page_slug(pr.title),
        "entity_type": pr.entity_type,
        "source_category": pr.source_category,
        "wiki_url": pr.wiki_url,
        "primary_image": pr.primary_image,
        "pick_reason": pr.pick_reason,
        "image_url": pr.image_url,
        "local_path": pr.local_path,
        "status": pr.status,
        "all_images_count": len(pr.all_images),
        "filtered_images_count": len(pr.filtered_images),
        "error": pr.error,
    }


def add_pr_to_index(index: dict[str, dict], pr: PageResult) -> None:
    if pr.status not in ("ok", "ok_url_only", "ok_cached"):
        return
    if not pr.local_path and not pr.image_url:
        return
    entry = {
        "title": pr.title,
        "entity_type": pr.entity_type,
        "image_file": pr.primary_image,
        "image_url": pr.image_url,
        "local_path": pr.local_path,
        "pick_reason": pr.pick_reason,
        "wiki_url": pr.wiki_url,
    }
    keys = {
        pr.title.lower(),
        wiki_page_slug(pr.title).lower(),
        f"{pr.entity_type}:{pr.title.lower()}",
        f"{pr.entity_type}:{wiki_page_slug(pr.title).lower()}",
    }
    for k in keys:
        index[k] = entry


def write_stats(
    results: list[PageResult],
    *,
    stats_path: Path,
    index: dict[str, dict],
    all_image_rows: int,
    args: argparse.Namespace,
) -> dict:
    failures = [page_result_row(pr) for pr in results if pr.status not in ("ok", "ok_url_only", "ok_cached")]
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "fail": 0})
    for pr in results:
        bucket = "ok" if pr.status in ("ok", "ok_url_only", "ok_cached") else "fail"
        by_type[pr.entity_type][bucket] += 1
    stats = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(results),
        "ok": sum(1 for r in results if r.status == "ok"),
        "ok_cached": sum(1 for r in results if r.status == "ok_cached"),
        "ok_url_only": sum(1 for r in results if r.status == "ok_url_only"),
        "no_primary": sum(1 for r in results if r.status == "no_primary"),
        "failed": len(failures),
        "index_keys": len(index),
        "all_image_rows": all_image_rows,
        "by_entity_type": dict(by_type),
        "skip_download": args.skip_download,
        "download_all_images": args.download_all_images,
        "data_dir": str(DATA_DIR),
        "resume": args.resume,
    }
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def enrich_cn_keys(index: dict[str, dict]) -> None:
    """Add CN alias keys from project dictionaries where EN title matches."""
    sys.path.insert(0, str(ROOT))
    try:
        from app.services.entity_dict import ASCENDANCY_CN_TO_EN, CLASS_CN_TO_EN
        from app.services.entity_resolver import _load_aliases
    except ImportError:
        logger.warning("Could not import alias tables — skipping CN key enrichment")
        return

    for cn, en in {**ASCENDANCY_CN_TO_EN, **CLASS_CN_TO_EN}.items():
        slug = wiki_page_slug(en)
        for key in (en.lower(), slug.lower()):
            if key in index:
                index[cn.lower()] = {**index[key], "alias_of": en, "alias_cn": cn}

    aliases = _load_aliases()
    for cn, (en, etype, _, _) in aliases.items():
        slug = wiki_page_slug(en)
        for key in (en.lower(), slug.lower(), f"{etype}:{en.lower()}"):
            if key in index:
                entry = {**index[key], "alias_of": en, "alias_cn": cn, "alias_type": etype}
                index[cn.lower()] = entry
                index[f"{etype}:{cn.lower()}"] = entry


def run(args: argparse.Namespace) -> int:
    global DATA_DIR, ICONS_DIR, WIKI_META_DIR
    if args.data_dir:
        DATA_DIR = resolve_data_dir(args.data_dir)
        ICONS_DIR = DATA_DIR / "icons" / "wiki"
        WIKI_META_DIR = DATA_DIR / "wiki_icons"

    client = WikiClient(delay=args.delay)
    jobs_cache = WIKI_META_DIR / "pages_cache.json"
    jobs = collect_pages(
        client,
        cache_path=jobs_cache,
        use_cache=not args.refresh_pages,
    )
    logger.info("Total wiki pages to process: %d", len(jobs))

    if args.collect_only:
        logger.info("collect-only — exiting after page cache")
        return 0

    if args.limit:
        jobs = jobs[: args.limit]

    manifest_path = WIKI_META_DIR / "manifest.jsonl"
    failures_path = WIKI_META_DIR / "failures.jsonl"
    retry_titles: set[str] | None = None
    if args.retry_failures:
        if not failures_path.is_file():
            logger.error("No failures.jsonl — nothing to retry")
            return 1
        retry_titles = {
            json.loads(line)["title"]
            for line in failures_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        jobs = [j for j in jobs if j.title in retry_titles]
        logger.info("Retry failures: %d pages from failures.jsonl", len(jobs))

    WIKI_META_DIR.mkdir(parents=True, exist_ok=True)
    scrape_log = WIKI_META_DIR / "scrape.log"
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        fh = logging.FileHandler(scrape_log, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(fh)

    manifest_path = WIKI_META_DIR / "manifest.jsonl"
    failures_path = WIKI_META_DIR / "failures.jsonl"
    all_images_path = WIKI_META_DIR / "all_images.jsonl"
    index_path = WIKI_META_DIR / "index.json"
    stats_path = WIKI_META_DIR / "stats.json"

    results: list[PageResult] = []
    all_image_rows: list[dict] = []
    index: dict[str, dict] = {}

    if args.retry_failures and retry_titles:
        preserved = [
            page_result_from_row(row)
            for row in load_manifest_rows(manifest_path)
            if row["title"] not in retry_titles
        ]
        results.extend(preserved)
        for pr in preserved:
            add_pr_to_index(index, pr)
        logger.info("Preserved %d manifest rows not in retry set", len(preserved))

    if args.resume and not args.retry_failures:
        for job in jobs:
            existing = find_existing_icon(job.entity_type, job.title)
            if not existing:
                continue
            wiki_url = (
                f"https://www.poe2wiki.net/wiki/"
                f"{urllib.parse.quote(job.title.replace(' ', '_'))}"
            )
            pr = PageResult(
                title=job.title,
                entity_type=job.entity_type,
                source_category=job.source_category,
                wiki_url=wiki_url,
                primary_image=existing.name,
                pick_reason="resume_cached",
                local_path=str(existing.relative_to(DATA_DIR)).replace("\\", "/"),
                status="ok_cached",
            )
            results.append(pr)
            add_pr_to_index(index, pr)
        done_titles = {r.title for r in results}
        jobs = [j for j in jobs if j.title not in done_titles]
        logger.info("Resume: %d cached on disk, %d pending", len(results), len(jobs))

    total_target = len(results) + len(jobs)

    manifest_path.write_text("", encoding="utf-8")
    if results:
        with manifest_path.open("a", encoding="utf-8") as mf:
            for pr in results:
                mf.write(json.dumps(page_result_row(pr), ensure_ascii=False) + "\n")
    failures: list[dict] = []
    lock_path = WIKI_META_DIR / "scrape.lock"
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age < 4 * 3600:
            logger.error("Another scrape appears active (lock age %.0fs)", age)
            return 2
        lock_path.unlink()
    lock_path.write_text(str(os.getpid()), encoding="utf-8")

    try:
        for i in range(0, len(jobs), args.batch_size):
            batch = jobs[i : i + args.batch_size]
            titles = [j.title for j in batch]
            images_map = client.pages_images(titles)

            primary_files: list[str] = []
            batch_results: list[PageResult] = []

            for job in batch:
                imgs = images_map.get(job.title, [])
                wiki_url = (
                    f"https://www.poe2wiki.net/wiki/"
                    f"{urllib.parse.quote(job.title.replace(' ', '_'))}"
                )
                filtered = filter_images(
                    imgs,
                    page_title=job.title,
                    entity_type=job.entity_type,
                )
                primary, reason = pick_primary_icon(job.title, job.entity_type, imgs)
                pr = PageResult(
                    title=job.title,
                    entity_type=job.entity_type,
                    source_category=job.source_category,
                    wiki_url=wiki_url,
                    all_images=imgs,
                    filtered_images=filtered,
                    primary_image=primary,
                    pick_reason=reason,
                )
                if primary:
                    primary_files.append(primary)
                else:
                    pr.status = "no_primary"
                batch_results.append(pr)

                for img in filtered:
                    all_image_rows.append(
                        {
                            "page_title": job.title,
                            "entity_type": job.entity_type,
                            "image_file": img,
                            "wiki_url": wiki_url,
                            "is_primary": img == primary,
                        },
                    )

            url_map = client.file_urls(list(set(primary_files)))
            extra_urls: dict[str, str] = {}
            if args.download_all_images:
                all_names = {img for pr in batch_results for img in pr.filtered_images}
                extra_urls = client.file_urls(list(all_names))

            for pr in batch_results:
                if not pr.primary_image:
                    results.append(pr)
                    continue
                pr.image_url = client.resolve_file_url(pr.primary_image, url_map)
                if not pr.image_url:
                    pr.status = "url_missing"
                    pr.error = f"no url for {pr.primary_image}"
                    results.append(pr)
                    continue

                if args.skip_download:
                    pr.status = "ok_url_only"
                    results.append(pr)
                    continue

                ext = Path(pr.primary_image).suffix.lower() or ".png"
                slug = wiki_page_slug(pr.title)
                dest = ICONS_DIR / pr.entity_type / f"{slug}{ext}"
                if args.resume and dest.is_file():
                    pr.local_path = str(dest.relative_to(DATA_DIR)).replace("\\", "/")
                    pr.status = "ok_cached"
                    results.append(pr)
                    continue
                try:
                    client.download(pr.image_url, dest)
                    pr.local_path = str(dest.relative_to(DATA_DIR)).replace("\\", "/")
                    pr.status = "ok"
                except Exception as exc:
                    pr.status = "download_failed"
                    pr.error = str(exc)[:200]

                if args.download_all_images:
                    page_dir = ICONS_DIR / "_all" / slug
                    for img in pr.filtered_images:
                        url = extra_urls.get(img)
                        if not url:
                            continue
                        try:
                            client.download(url, page_dir / img.replace("/", "_"))
                        except Exception:
                            pass

                results.append(pr)

            with manifest_path.open("a", encoding="utf-8") as mf:
                for pr in batch_results:
                    row = page_result_row(pr)
                    mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    if pr.status not in ("ok", "ok_url_only", "ok_cached"):
                        failures.append(row)
                    add_pr_to_index(index, pr)

            enrich_cn_keys(index)
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
            write_stats(
                results,
                stats_path=stats_path,
                index=index,
                all_image_rows=len(all_image_rows),
                args=args,
            )

            ok = sum(1 for r in results if r.status in ("ok", "ok_cached"))
            logger.info("Progress %d/%d (icons %d)", len(results), total_target, ok)

    finally:
        lock_path.unlink(missing_ok=True)
        failures = [
            page_result_row(pr)
            for pr in results
            if pr.status not in ("ok", "ok_url_only", "ok_cached")
        ]
        with failures_path.open("w", encoding="utf-8") as ff:
            for row in failures:
                ff.write(json.dumps(row, ensure_ascii=False) + "\n")
        with all_images_path.open("w", encoding="utf-8") as af:
            for row in all_image_rows:
                af.write(json.dumps(row, ensure_ascii=False) + "\n")

    stats = write_stats(
        results,
        stats_path=stats_path,
        index=index,
        all_image_rows=len(all_image_rows),
        args=args,
    )
    logger.info("Done. stats=%s", json.dumps(stats, ensure_ascii=False))
    logger.info("manifest → %s", manifest_path)
    logger.info("index   → %s (%d keys)", index_path, len(index))
    return 0 if stats["failed"] < stats["total_pages"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape poe2wiki entity icons")
    parser.add_argument("--limit", type=int, default=0, help="Max pages (0=all)")
    parser.add_argument("--batch-size", type=int, default=50, help="Pages per API batch")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between API calls")
    parser.add_argument("--data-dir", type=str, default="", help="Output data root (default: repo/data or backend/data)")
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Only walk wiki categories and write pages_cache.json, then exit",
    )
    parser.add_argument(
        "--refresh-pages",
        action="store_true",
        help="Re-walk wiki categories instead of using pages_cache.json",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip pages whose icon file already exists on disk",
    )
    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="Re-process pages listed in failures.jsonl and merge into manifest/index",
    )
    parser.add_argument("--skip-download", action="store_true", help="Manifest only, no PNG download")
    parser.add_argument(
        "--download-all-images",
        action="store_true",
        help="Also save every filtered image on each page under icons/wiki/_all/",
    )
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
