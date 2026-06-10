"""Quick check: what items are in caimogu_items.json?"""
import json
with open("/app/data/caimogu_items.json", "r", encoding="utf-8") as f:
    items = json.load(f)
print(f"Total: {len(items)}")

# Find twisted
for it in items:
    en = it.get("en", "").lower()
    cn = it.get("cn", "")
    if "twist" in en:
        print(f"TWIST: {cn} <-> {it.get('en')}")

# Find necklace/amulet
for it in items:
    en = it.get("en", "").lower()
    cn = it.get("cn", "")
    if "neck" in en or "amu" in en:
        print(f"NECK: {cn} <-> {it.get('en')}")

# Find by CN containing specific chars
for it in items:
    cn = it.get("cn", "")
    if "扭曲" in cn or "项链" in cn or "护身符" in cn:
        print(f"CN_MATCH: {cn} <-> {it.get('en')}")
