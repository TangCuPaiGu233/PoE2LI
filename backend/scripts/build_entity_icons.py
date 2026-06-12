"""Build entity_icons.json + download official icons from poe2db.tw (poecdn).

Usage:
  python backend/scripts/build_entity_icons.py
  python backend/scripts/build_entity_icons.py --limit 50   # smoke test
  python backend/scripts/build_entity_icons.py --workers 24 --icon-workers 96
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import get_close_matches
from pathlib import Path

import cloudscraper
import requests

# Allow running from repo root or backend/
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ICONS_DIR = DATA_DIR / "icons"

POECDN_ICON_RE = re.compile(
    r"https://web\.poecdn\.com/gen/image/[^\"'\s\]]+\.(?:png|webp)",
    re.IGNORECASE,
)
ICON_BLOCKLIST = frozenset({"vendor.png", "currencyitem.png", "blank.png"})
INDEX_PAGES = [
    "Skill_Gems",
    "Support_Gems",
    "Spirit_Gems",
    "Unique_item",
    "Ascendancy_class",
]
# Pages that reliably embed poecdn item/skill icons (exclude ascendancy passives list).
ICON_INDEX_PAGES = [
    "Skill_Gems",
    "Support_Gems",
    "Spirit_Gems",
    "Unique_item",
]
PAGE_ETYPE = {
    "Skill_Gems": "skill",
    "Support_Gems": "skill",
    "Spirit_Gems": "skill",
    "Unique_item": "item",
    "Ascendancy_class": "ascendancy",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("build_entity_icons")

_thread_local = threading.local()


def poe2db_slug(name_en: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name_en).strip("_")


def normalize_icon_url(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    if not u:
        return None
    if u.rsplit("/", 1)[-1].lower() in ICON_BLOCKLIST:
        return None
    return u


def extract_icon(html: str, etype: str = "item") -> str | None:
    sys.path.insert(0, str(ROOT))
    from app.services.entity_icon_service import extract_icon_from_text

    return extract_icon_from_text(html or "", etype)


def get_scraper() -> cloudscraper.CloudScraper:
    if not getattr(_thread_local, "scraper", None):
        _thread_local.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False},
        )
    return _thread_local.scraper


@dataclass
class Entity:
    name_en: str
    name_cn: str
    etype: str
    path: str = ""

    def __post_init__(self) -> None:
        if not self.path:
            self.path = poe2db_slug(self.name_en)


@dataclass
class Result:
    entity: Entity
    icon_url: str | None = None
    local_file: str | None = None
    status: str = "pending"
    error: str | None = None
    http_status: int | None = None


def load_entities() -> list[Entity]:
    sys.path.insert(0, str(ROOT))
    from app.services.entity_dict import ASCENDANCY_CN_TO_EN

    seen: set[tuple[str, str]] = set()
    out: list[Entity] = []

    def add(name_en: str, name_cn: str, etype: str, path: str = "") -> None:
        name_en = (name_en or "").strip()
        name_cn = (name_cn or "").strip()
        if not name_en:
            return
        key = (etype, name_en.lower())
        if key in seen:
            return
        seen.add(key)
        out.append(Entity(name_en=name_en, name_cn=name_cn, etype=etype, path=path or ""))

    skills_path = DATA_DIR / "caimogu_skills.json"
    if skills_path.is_file():
        for row in json.loads(skills_path.read_text(encoding="utf-8")):
            add(row.get("en", ""), row.get("cn", ""), "skill")

    uniques_path = DATA_DIR / "unique_cn_en.json"
    if uniques_path.is_file():
        data = json.loads(uniques_path.read_text(encoding="utf-8"))
        for cn, info in (data.get("cn_to_en") or {}).items():
            add(info.get("en", ""), cn, "item", path=info.get("path", "") or "")

    for cn, en in ASCENDANCY_CN_TO_EN.items():
        add(en, cn, "ascendancy")

    return out


@dataclass
class IndexEntry:
    path: str
    name_en: str
    name_cn: str
    etype: str
    index_page: str


def fetch_index_entries(
    pages: list[str] | None = None,
) -> tuple[dict[str, str], list[IndexEntry]]:
    """Collect EN name→path map and per-path index rows (EN+CN names)."""
    en_to_path: dict[str, str] = {}
    by_path: dict[str, IndexEntry] = {}
    scraper = get_scraper()
    for page in pages or INDEX_PAGES:
        etype = PAGE_ETYPE.get(page, "item")
        names_by_lang: dict[str, dict[str, str]] = {"us": {}, "cn": {}}
        for lang in ("us", "cn"):
            url = f"https://poe2db.tw/{lang}/{page}"
            try:
                resp = scraper.get(url, timeout=25)
                if resp.status_code != 200:
                    logger.warning("index %s/%s -> %s", lang, page, resp.status_code)
                    continue
                for m in re.finditer(
                    rf'href="/{lang}/([^"]+)"[^>]*>([^<]+)</a>',
                    resp.text,
                ):
                    path, name = m.group(1), m.group(2).strip()
                    if not path or not name or len(name) < 2:
                        continue
                    if path == page:
                        continue
                    names_by_lang[lang][path] = name
            except Exception as exc:
                logger.warning("index %s/%s failed: %s", lang, page, exc)
        for path, name_en in names_by_lang["us"].items():
            en_to_path[name_en.lower()] = path
            by_path[path] = IndexEntry(
                path=path,
                name_en=name_en,
                name_cn=names_by_lang["cn"].get(path, ""),
                etype=etype,
                index_page=page,
            )
        for path, name_cn in names_by_lang["cn"].items():
            if path not in by_path:
                by_path[path] = IndexEntry(
                    path=path,
                    name_en=poe2db_slug(name_cn).replace("_", " "),
                    name_cn=name_cn,
                    etype=etype,
                    index_page=page,
                )
    logger.info("index paths collected: %d entries", len(by_path))
    return en_to_path, list(by_path.values())


def fetch_index_paths() -> dict[str, str]:
    en_to_path, _ = fetch_index_entries()
    return en_to_path


def load_entities_from_index(entries: list[IndexEntry]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in entries:
        if row.path in seen:
            continue
        seen.add(row.path)
        out.append(
            Entity(
                name_en=row.name_en,
                name_cn=row.name_cn,
                etype=row.etype,
                path=row.path,
            ),
        )
    return out


def path_candidates(entity: Entity, index_paths: dict[str, str]) -> list[str]:
    cands: list[str] = []
    for p in (entity.path, index_paths.get(entity.name_en.lower(), "")):
        if p and p not in cands:
            cands.append(p)
    slug = poe2db_slug(entity.name_en).lower()
    for key, path in index_paths.items():
        if key == entity.name_en.lower() or poe2db_slug(key) == slug:
            if path not in cands:
                cands.append(path)
    close = get_close_matches(entity.name_en.lower(), index_paths.keys(), n=2, cutoff=0.88)
    for key in close:
        path = index_paths[key]
        if path not in cands:
            cands.append(path)
    if entity.path not in cands:
        cands.insert(0, entity.path)
    return cands[:6]


def fetch_detail_icon(entity: Entity, index_paths: dict[str, str], backoff: list[float]) -> Result:
    res = Result(entity=entity)
    scraper = get_scraper()
    for path in path_candidates(entity, index_paths):
        entity.path = path
        for lang in ("cn", "us"):
            url = f"https://poe2db.tw/{lang}/{path}"
            for attempt in range(4):
                try:
                    resp = scraper.get(url, timeout=25)
                    res.http_status = resp.status_code
                    if resp.status_code == 429:
                        time.sleep(backoff[0])
                        backoff[0] = min(backoff[0] * 2, 30)
                        continue
                    if resp.status_code != 200:
                        break
                    icon = extract_icon(resp.text, entity.etype)
                    if icon:
                        res.icon_url = icon
                        res.status = "ok"
                        return res
                    break
                except Exception as exc:
                    res.error = str(exc)[:200]
                    time.sleep(min(2 ** attempt, 8))
        if res.status == "ok":
            break
    if not res.icon_url:
        res.status = "not_found"
        res.error = res.error or "no_poecdn_in_html"
    return res


def download_icon(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "PoE2LI-IconCrawler/1.0"},
        )
        if resp.status_code != 200:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return True
    except Exception:
        return False


def build_flat_map(results: list[Result]) -> dict[str, str]:
    flat: dict[str, str] = {}
    for r in results:
        if not r.icon_url:
            continue
        e = r.entity
        keys = (
            f"{e.etype}:{e.name_en.lower()}",
            e.name_en.lower(),
            e.path.lower(),
            poe2db_slug(e.name_en).lower(),
        )
        if e.name_cn:
            keys = (*keys, e.name_cn.lower())
        for k in keys:
            if k and k not in flat:
                flat[k] = r.icon_url
    return flat


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max entities (0=all)")
    parser.add_argument("--workers", type=int, default=24, help="poe2db detail workers")
    parser.add_argument("--icon-workers", type=int, default=96, help="poecdn download workers")
    parser.add_argument("--skip-download", action="store_true", help="URLs only, no PNG files")
    parser.add_argument(
        "--from-index",
        action="store_true",
        help="Crawl poe2db index pages only (correct paths, higher hit rate)",
    )
    args = parser.parse_args()

    index_paths, index_entries = fetch_index_entries()
    if args.from_index:
        _, icon_entries = fetch_index_entries(ICON_INDEX_PAGES)
        entities = load_entities_from_index(icon_entries)
    else:
        entities = load_entities()
    for ent in entities:
        hit = index_paths.get(ent.name_en.lower())
        if hit:
            ent.path = hit

    if args.limit:
        entities = entities[: args.limit]

    logger.info("entities to fetch: %d", len(entities))

    backoff = [1.0]
    detail_results: list[Result] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_detail_icon, ent, index_paths, backoff): ent for ent in entities
        }
        done = 0
        for fut in as_completed(futures):
            detail_results.append(fut.result())
            done += 1
            if done % 100 == 0:
                ok = sum(1 for r in detail_results if r.icon_url)
                logger.info("detail progress %d/%d ok=%d", done, len(entities), ok)

    ok_detail = [r for r in detail_results if r.icon_url]
    logger.info("detail done: ok=%d fail=%d", len(ok_detail), len(detail_results) - len(ok_detail))

    if not args.skip_download and ok_detail:
        def dl(r: Result) -> Result:
            ext = ".webp" if r.icon_url.lower().endswith(".webp") else ".png"
            rel = f"icons/{r.entity.etype}/{r.entity.path}{ext}"
            dest = DATA_DIR / rel
            if download_icon(r.icon_url, dest):
                r.local_file = rel.replace("\\", "/")
            return r

        with ThreadPoolExecutor(max_workers=args.icon_workers) as pool:
            list(pool.map(dl, ok_detail))

    manifest_path = DATA_DIR / "entity_icons_manifest.jsonl"
    failures_path = DATA_DIR / "entity_icons_failures.jsonl"
    icons_json_path = DATA_DIR / "entity_icons.json"
    now = datetime.now(timezone.utc).isoformat()

    with manifest_path.open("w", encoding="utf-8") as mf, failures_path.open("w", encoding="utf-8") as ff:
        for r in detail_results:
            row = {
                "name_en": r.entity.name_en,
                "name_cn": r.entity.name_cn,
                "type": r.entity.etype,
                "poe2db_path": r.entity.path,
                "icon_url": r.icon_url,
                "local_file": r.local_file,
                "status": r.status,
                "http_status": r.http_status,
                "error": r.error,
                "fetched_at": now,
            }
            mf.write(json.dumps(row, ensure_ascii=False) + "\n")
            if r.status != "ok":
                ff.write(json.dumps(row, ensure_ascii=False) + "\n")

    flat = build_flat_map(detail_results)
    if icons_json_path.is_file():
        try:
            prev = json.loads(icons_json_path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                merged = {str(k).lower(): v for k, v in prev.items() if v}
                merged.update(flat)
                flat = merged
        except (json.JSONDecodeError, OSError):
            pass
    icons_json_path.write_text(
        json.dumps(flat, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ok = len(ok_detail)
    logger.info(
        "wrote %s (%d keys), manifest %d lines, failures %d",
        icons_json_path,
        len(flat),
        len(detail_results),
        len(detail_results) - ok,
    )
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
