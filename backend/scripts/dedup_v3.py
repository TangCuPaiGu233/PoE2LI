"""Deduplicate poe2db_chunks_v3.jsonl by detail_path."""
import json, sys, shutil

path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/poe2db_chunks_v3.jsonl"
seen = set()
uniq = []

with open(path, "r", encoding="utf-8") as f:
    for l in f:
        if l.strip():
            try:
                c = json.loads(l)
                p = c.get("detail_path", "")
                if p and p not in seen:
                    seen.add(p)
                    uniq.append(l)
            except Exception:
                pass

# Backup original
shutil.copy(path, path + ".bak")

# Write deduplicated
with open(path, "w", encoding="utf-8") as f:
    for l in uniq:
        f.write(l)

print(f"Deduplicated: {len(uniq)} unique entries (was {len(seen)} seen)")
