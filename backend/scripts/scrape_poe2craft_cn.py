"""Scrape PoE2 CN translations from craftofexile.com.

Fetches poe2c_lang.cn.json (CN translations) and poe2c_data.json (item data),
cross-references them, and saves clean EN->CN mapping files.
"""
import json, requests

BASE = "https://www.craftofexile.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_json(path):
    url = f"{BASE}/{path}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    text = r.text
    # Strip JS variable prefix if present (e.g. "poecl=", "poe2cl=")
    if text[0] not in '{[':
        text = text[text.index("{"):]
    return json.loads(text)

# Try all possible PoE2 CN lang URLs
lang_urls = [
    "json/data/lang/poe2c_lang.cn.json",
    "json/data/lang/poe2_lang.cn.json",
]
data_urls = [
    "json/data/poe2c_data.json",
    "json/data/poe2_data.json",
]

lang_data = None
for url in lang_urls:
    try:
        print(f"Trying {url}...")
        lang_data = fetch_json(url)
        print(f"  OK: {len(lang_data)} keys: {list(lang_data.keys())}")
        break
    except Exception as e:
        print(f"  Failed: {e}")

data_ok = None
for url in data_urls:
    try:
        print(f"Trying {url}...")
        data_ok = fetch_json(url)
        print(f"  OK: keys={list(data_ok.keys())[:10]}")
        break
    except Exception as e:
        print(f"  Failed: {e}")

if lang_data:
    with open("/app/data/poe2craft_cn_lang.json", "w", encoding="utf-8") as f:
        json.dump(lang_data, f, ensure_ascii=False)
    total = sum(len(v) if isinstance(v, dict) else 1 for v in lang_data.values())
    print(f"\nSaved lang: {total} entries")

if data_ok:
    # Save slim version (just bases and bitems for cross-ref)
    slim = {
        "bases": data_ok.get("bases", {}),
        "bitems": data_ok.get("bitems", {}),
        "aliases": data_ok.get("aliases", {}),
    }
    with open("/app/data/poe2craft_data_slim.json", "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False)
    print(f"Saved data slim")
