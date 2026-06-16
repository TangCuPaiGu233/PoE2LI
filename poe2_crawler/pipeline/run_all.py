"""Full pipeline dry-run against all configured entity types."""
import asyncio, json, logging, sys, yaml
from pathlib import Path

logger = logging.getLogger("run_all")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crawler.fetcher import Fetcher
from parser.base_parser import parse_entity_list
from parser.parsers.ascendancy_parser import parse_ascendancy_index
from parser.parsers.homepage_parser import parse_homepage

# Types that need custom parsing
_CUSTOM = {"ascendancy", "class", "homepage"}


async def main():
    with open("config/entity_types.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    fetcher = Fetcher()
    all_entities: dict[str, dict] = {}  # entity_id -> {name, type}
    all_edges: list[dict] = []

    for etype, spec in config["entity_types"].items():
        # Prefer /us/ URLs (English = most complete data), fall back to /cn/
        urls = spec.get("index_urls", [])
        us_first = [u for u in urls if "/us/" in u] + [u for u in urls if "/us/" not in u]
        for url in us_first:
            print(f"\n{etype}: {url} ...", end=" ", flush=True)
            html = await fetcher.fetch(url)
            if not html:
                print("FAIL (fetch)")
                continue

            # Parse
            if etype == "homepage":
                parsed = parse_homepage(html)
            elif etype in _CUSTOM:
                parsed = parse_ascendancy_index(html)
            else:
                parsed = parse_entity_list(html, etype, poe2_tab_only=True)

            ents = parsed.get("entities", {})
            edges = parsed.get("edges", [])
            print(f"{len(ents)} entities, {len(edges)} edges", flush=True)

            for eid, info in ents.items():
                if eid not in all_entities:
                    all_entities[eid] = info
                else:
                    # Merge: keep existing, fill in missing name from new
                    existing = all_entities[eid]
                    if not existing.get("name") and info.get("name"):
                        existing["name"] = info["name"]
                    # Prefer English name from /us/ URLs
                    if "/us/" in url and info.get("name"):
                        existing["name"] = info["name"]
            all_edges.extend(edges)

    await fetcher.close()

    # ═══ Phase B: Detail page edge extraction ═══
    print("\n=== Phase B: Detail edges ===")
    detail_types = {"skill": 0, "spirit_gem": 0, "unique": 0, "monster": 50}
    detail_edges_total = 0

    for etype, sample_n in detail_types.items():
        candidates = [(eid, info) for eid, info in all_entities.items()
                      if info.get("type") == etype and "/" not in eid.split(":", 1)[1]]
        if sample_n > 0:
            candidates = candidates[:sample_n]
        print(f"\n{etype}: sampling {len(candidates)} detail pages...")
        for eid, info in candidates:
            slug = eid.split(":", 1)[1]
            url = f"https://poe2db.tw/us/{slug}"
            html = await fetcher.fetch(url)
            if not html:
                continue
            from parser.detail_parser import parse_page_edges
            edges = parse_page_edges(html, eid, etype)
            if edges:
                all_edges.extend(edges)
                detail_edges_total += len(edges)
        print(f"  -> {detail_edges_total} new edges so far")

    # ═══ Quest Rewards table (special: single page with many edges) ═══
    print("\n=== Quest Rewards ===")
    qr_html = await fetcher.fetch("https://poe2db.tw/us/QuestRewards")
    if qr_html:
        from parser.detail_parser import parse_quest_rewards_table
        qr_edges = parse_quest_rewards_table(qr_html)
        all_edges.extend(qr_edges)
        detail_edges_total += len(qr_edges)
        print(f"  Quest rewards: {len(qr_edges)} edges")

    print(f"\nPhase B done: {detail_edges_total} detail edges extracted")

    # ═══ Save full data for loader ═══
    import json
    full_entities = {eid: info for eid, info in all_entities.items()}
    Path("data/discovery_full.json").write_text(
        json.dumps({"entities": full_entities, "by_type": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved %d entities to data/discovery_full.json", len(full_entities))

    with open("data/raw_edges.jsonl", "w", encoding="utf-8") as f:
        for e in all_edges:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    logger.info("Saved %d edges to data/raw_edges.jsonl", len(all_edges))

    # ═══ Summary ═══
    print(f"\n=== TOTAL ===")
    print(f"Entities: {len(all_entities)}")
    print(f"Edges: {len(all_edges)}")

    # By type
    type_counts: dict[str, int] = {}
    for eid, info in all_entities.items():
        t = info.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")

    # Save
    out = Path("data/discovery_dryrun.json")
    out.write_text(json.dumps({
        "total_entities": len(all_entities),
        "total_edges": len(all_edges),
        "by_type": type_counts,
        "entities": {k: v for k, v in list(all_entities.items())[:20]},
        "edges": all_edges[:20],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
