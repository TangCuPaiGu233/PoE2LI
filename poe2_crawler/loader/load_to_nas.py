"""Load pipeline output (entities + edges) to NAS kb_entities/kb_edges."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import paramiko
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from normalize.edge_normalizer import normalize_edges

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("loader")

NAS_HOST = "192.168.110.26"
NAS_PORT = 2212
NAS_USER = "skc"
NAS_PASS = "SKChaidao@123"
DOCKER = "/usr/local/bin/docker"
DB_CONTAINER = "poe2li-postgres"
DB_NAME = "poe2li"
DB_USER = "poe2li"


def run_sql(sql: str) -> str:
    """Execute SQL on NAS Postgres via temp file (avoids shell quoting issues)."""
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(NAS_HOST, NAS_PORT, NAS_USER, NAS_PASS, timeout=10)
    import base64
    b64 = base64.b64encode(sql.encode()).decode()
    cmd = f"echo '{b64}' | base64 -d | {DOCKER} exec -i {DB_CONTAINER} psql -U {DB_USER} -d {DB_NAME}"
    _, o, e = c.exec_command(cmd)
    out = o.read().decode(errors="replace")
    err = e.read().decode(errors="replace")
    c.close()
    if err and ("ERROR" in err or "FATAL" in err):
        logger.error("SQL error: %s", err[:300])
    return out


def main():
    # 1. Load entities
    entities_path = Path("data/discovery_full.json")
    if not entities_path.exists():
        logger.error("Run pipeline first: python pipeline/run_all.py")
        return
    discovery = json.loads(entities_path.read_text(encoding="utf-8"))
    logger.info("Loaded %d entities from discovery", len(discovery.get("entities", {})))

    # 2. Load raw edges
    edges_path = Path("data/raw_edges.jsonl")
    raw_edges: list[dict] = []
    if edges_path.exists():
        with open(edges_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    raw_edges.append(json.loads(line))
    logger.info("Loaded %d raw edges", len(raw_edges))

    # 3. Normalize edges
    normalized = normalize_edges(raw_edges)
    logger.info("Normalized to %d edges", len(normalized))

    # 4. Clear old kb_entities and kb_edges
    logger.info("Clearing old kb_entities and kb_edges...")
    run_sql("DELETE FROM kb_edges;")
    run_sql("DELETE FROM kb_entities;")
    logger.info("Old data cleared")

    # 5. Insert entities (batched)
    entities = list(discovery.get("entities", {}).items())
    batch_size = 500
    inserted_e = 0
    for i in range(0, len(entities), batch_size):
        batch = entities[i:i + batch_size]
        values = []
        for eid, info in batch:
            etype = info.get("type", "unknown")
            name_en = info.get("name", "").split(":", 1)[-1] if ":" in eid else eid.split(":", 1)[-1]
            name_cn = info.get("name", "") if info.get("name", "") else None
            entity_key = eid.replace(":", "_", 1).lower()
            aliases = json.dumps([name_cn] if name_cn else [], ensure_ascii=False)
            # Escape single quotes
            safe_key = entity_key.replace("'", "''").replace("\\", "\\\\")
            safe_type = etype.replace("'", "''")
            safe_en = name_en.replace("'", "''").replace("\\", "\\\\")
            safe_cn = (name_cn or "").replace("'", "''").replace("\\", "\\\\")
            safe_aliases = aliases.replace("'", "''")
            cn_val = "NULL" if not name_cn else "'" + safe_cn + "'"
            values.append(
                "('" + safe_key + "', '" + safe_type + "', '" + safe_en + "', "
                + cn_val + ", "
                + "'" + safe_aliases + "', 'Standard', '0_1')"
            )
        sql = (
            "INSERT INTO kb_entities (entity_key, entity_type, name_en, name_cn, aliases, league, game_version) VALUES "
            + ", ".join(values)
            + " ON CONFLICT (entity_key) DO UPDATE SET name_cn = EXCLUDED.name_cn, name_en = EXCLUDED.name_en;"
        )
        run_sql(sql)
        inserted_e += len(batch)
        logger.info("Entities: %d/%d", inserted_e, len(entities))

    # 6. Insert edges (batched)
    edge_batch_size = 500
    inserted_edges = 0
    for i in range(0, len(normalized), edge_batch_size):
        batch = normalized[i:i + edge_batch_size]
        values = []
        for e in batch:
            sk = e["src_entity_key"].replace("'", "''")
            dk = e["dst_entity_key"].replace("'", "''")
            rel = e["relation"].replace("'", "''")
            w = e.get("weight", 1.0)
            values.append(
                "SELECT s.id, d.id, '" + rel + "', " + str(w) + ", NULL::integer"
                " FROM kb_entities s, kb_entities d"
                " WHERE s.entity_key = '" + sk + "' AND d.entity_key = '" + dk + "'"
            )
        sql = (
            "INSERT INTO kb_edges (src_entity_id, dst_entity_id, relation, weight, source_chunk_id) "
            + " UNION ALL ".join(values)
            + ";"
        )
        run_sql(sql)
        inserted_edges += len(batch)
        logger.info("Edges: %d/%d", inserted_edges, len(normalized))

    # 7. Verify
    print()
    print("=== Verification ===")
    print(run_sql("SELECT count(*) as entity_count FROM kb_entities;"))
    print(run_sql("SELECT count(*) as edge_count FROM kb_edges;"))
    print(run_sql("SELECT entity_type, count(*) FROM kb_entities GROUP BY entity_type ORDER BY count(*) DESC LIMIT 15;"))
    print(run_sql("SELECT relation, count(*) FROM kb_edges GROUP BY relation ORDER BY count(*) DESC;"))
    print("DONE")


if __name__ == "__main__":
    main()
