"""Re-scrape specific unique pages and merge into poe2db_uniques.jsonl."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scrape_poe2db_uniques import (
    scrape_unique_variants,
    _build_search_text,
    _save,
    _slug,
    resolve_unique_name,
)

DEFAULT_PATHS = [
    "Seeing_Stars",
    "Constricting_Command",
    "Bones_of_Ullr",
    "Choir_of_the_Storm",
    "Uhtreds_Chalice",
]

JSONL = os.path.join(os.path.dirname(__file__), "..", "data", "poe2db_uniques.jsonl")


def _index_name_for_path(path: str) -> str:
    """Best-effort EN index label from path slug."""
    from urllib.parse import unquote
    return unquote(path).replace("_", " ")


def scrape_paths(paths: list[str]) -> list[dict]:
    chunks: list[dict] = []
    for path in paths:
        en_variants = scrape_unique_variants(path, "us")
        cn_variants = scrape_unique_variants(path, "cn")
        tw_variants = scrape_unique_variants(path, "tw")
        time.sleep(0.3)
        if not en_variants:
            print(f"  FAIL no variants: {path}")
            continue
        index_name = _index_name_for_path(path)
        canonical_en = resolve_unique_name(index_name, path, en_variants[0].get("name"))
        parent_id = f"unique_{path}"
        parent_cn = cn_variants[0].get("name") if cn_variants else None
        print(f"  OK {path} -> {canonical_en} ({len(en_variants)} variants)")
        for vi, en in enumerate(en_variants):
            cn = cn_variants[vi] if vi < len(cn_variants) else (cn_variants[0] if cn_variants else None)
            tw = tw_variants[vi] if vi < len(tw_variants) else (tw_variants[0] if tw_variants else None)
            base_slug = _slug(",".join(en.get("item_type") or []) or f"v{vi}")
            chunk_id = f"{parent_id}_{base_slug}" if len(en_variants) > 1 else parent_id
            chunks.append({
                "chunk_id": chunk_id,
                "content_type": "item",
                "source_page": "Unique_item",
                "item_path": path,
                "parent_entity_id": parent_id,
                "variant_index": vi,
                "name_en": canonical_en,
                "variant_base_type": en.get("item_type", [None])[0] if en.get("item_type") else None,
                "search_text": _build_search_text(en, cn, tw, canonical_en, parent_cn)[:4000],
                "en_data": json.dumps(en, ensure_ascii=False),
                "cn_data": json.dumps(cn, ensure_ascii=False) if cn else "",
                "tw_data": json.dumps(tw, ensure_ascii=False) if tw else "",
            })
    return chunks


def merge_jsonl(new_chunks: list[dict], jsonl_path: str) -> int:
    by_id: dict[str, dict] = {}
    if os.path.exists(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    by_id[d["chunk_id"]] = d
    for c in new_chunks:
        by_id[c["chunk_id"]] = c
    merged = list(by_id.values())
    _save(merged, jsonl_path)
    return len(new_chunks)


def main():
    paths = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_PATHS
    jsonl_path = os.environ.get("UNIQUES_JSONL", JSONL)
    print(f"Re-scraping {len(paths)} paths...")
    new_chunks = scrape_paths(paths)
    if not new_chunks:
        print("No chunks produced")
        sys.exit(1)
    n = merge_jsonl(new_chunks, jsonl_path)
    print(f"Merged {n} chunks into {jsonl_path} (total file updated)")


if __name__ == "__main__":
    main()
