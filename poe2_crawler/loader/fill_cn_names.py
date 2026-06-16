"""Extract CN entity names from poe2db CN pages and update kb_entities."""
import sys, asyncio, re, json, paramiko, base64
from pathlib import Path
from collections import OrderedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crawler.fetcher import Fetcher
from bs4 import BeautifulSoup

NAS_HOST = "192.168.110.26"; NAS_PORT = 2212; NAS_USER = "skc"; NAS_PASS = "SKChaidao@123"
D = "/usr/local/bin/docker"; DB = "poe2li-postgres"

def run_sql(sql):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(NAS_HOST, NAS_PORT, NAS_USER, NAS_PASS, timeout=10)
    b64 = base64.b64encode(sql.encode()).decode()
    _, o, e = c.exec_command(f"echo '{b64}' | base64 -d | {D} exec -i {DB} psql -U poe2li -d poe2li")
    c.close()
    return o.read().decode(errors="replace")


def extract_cn_names_from_page(html: str) -> list[str]:
    """Extract CN names from poe2db CN Notable/Keystone page text."""
    soup = BeautifulSoup(html, "lxml")
    tabs = soup.find_all("div", class_="tab-pane")
    if not tabs:
        return []
    text = tabs[0].get_text()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # Filter to lines with CJK characters, skip header/footer
    cjk = []
    for l in lines:
        if not any('一' <= c <= '鿿' for c in l):
            continue
        # Skip known non-name lines
        if l.startswith("被动天赋") or l.startswith("Passive") or "/" in l[:5]:
            continue
        # First part before attribute tags is the name
        # Pattern: name + attribute tags + description
        cjk.append(l)
    return cjk


def extract_en_names_from_page(html: str) -> list[str]:
    """Extract EN names from poe2db EN Notable page links."""
    soup = BeautifulSoup(html, "lxml")
    tabs = soup.find_all("div", class_="tab-pane")
    if not tabs:
        return []
    names = []
    seen = set()
    for a in tabs[0].find_all("a", href=re.compile(r"/(us|cn)/")):
        href = a["href"]
        slug = href.rstrip("/").split("/")[-1]
        text = a.get_text(strip=True)
        if slug in seen or not text or len(text) < 2:
            continue
        seen.add(slug)
        names.append(text)
    return names


async def main():
    fetcher = Fetcher()
    updated = 0

    for page_type in ["Notable", "Keystone"]:
        print(f"\n=== {page_type} ===")
        cn_html = await fetcher.fetch(f"https://poe2db.tw/cn/{page_type}")
        en_html = await fetcher.fetch(f"https://poe2db.tw/us/{page_type}")
        if not cn_html or not en_html:
            print(f"  Failed to fetch {page_type}")
            continue

        # EN: get names and slugs from links
        en_soup = BeautifulSoup(en_html, "lxml")
        en_tabs = en_soup.find_all("div", class_="tab-pane")
        en_pairs = []  # (slug, en_name)
        seen_slugs = set()
        for a in en_tabs[0].find_all("a", href=re.compile(r"/(us|cn)/")) if en_tabs else []:
            slug = a["href"].rstrip("/").split("/")[-1]
            text = a.get_text(strip=True)
            if slug in seen_slugs or not text or len(text) < 2:
                continue
            seen_slugs.add(slug)
            en_pairs.append((slug, text))

        # CN: get name text lines
        cn_lines = extract_cn_names_from_page(cn_html)
        cn_names = []
        for line in cn_lines:
            # Extract just the name part (before attribute tags)
            # Attribute tags are short CJK words like: 坚韧 持久 贪婪...
            # Name is the first part, then attributes, then description
            # Name + attributes are CJK, description starts with +number or CJK compound
            parts = line.split()
            name_parts = []
            for p in parts:
                # Stop at first number or long description
                if re.match(r'[\d+\-]', p) or len(p) > 10:
                    break
                if any('一' <= c <= '鿿' for c in p):
                    name_parts.append(p)
                else:
                    break
            cn_name = "".join(name_parts) if name_parts else line[:15]
            cn_names.append(cn_name)

        print(f"  EN: {len(en_pairs)} names, CN: {len(cn_names)} names")

        # Pair by position (order should match between EN and CN pages)
        pairs = list(zip(en_pairs, cn_names[:len(en_pairs)]))
        print(f"  Paired: {len(pairs)}")

        # Update kb_entities
        for (slug, en_name), cn_name in pairs:
            if cn_name and cn_name != en_name:
                entity_key = f"passive_{slug}".lower()
                safe_cn = cn_name.replace("'", "''")
                safe_key = entity_key.replace("'", "''")
                sql = f"UPDATE kb_entities SET name_cn = '{safe_cn}' WHERE entity_key = '{safe_key}' AND (name_cn IS NULL OR name_cn = '');"
                run_sql(sql)
                updated += 1

        print(f"  Updated so far: {updated}")

    await fetcher.close()
    print(f"\nTotal updated: {updated}")

    # Also update class entities with CN names
    print("\n=== Classes ===")
    classes_cn = {"ranger": "游侠", "huntress": "女猎手", "monk": "行者", "witch": "女巫",
                   "sorceress": "魔巫", "warrior": "战士", "mercenary": "佣兵", "druid": "德鲁伊"}
    for en, cn in classes_cn.items():
        run_sql(f"UPDATE kb_entities SET name_cn = '{cn}' WHERE entity_key = 'class_{en}' AND (name_cn IS NULL OR name_cn = '');")
        updated += 1
    print(f"Classes updated: {len(classes_cn)}")

    print(f"\nFinal total updated: {updated}")


if __name__ == "__main__":
    asyncio.run(main())
