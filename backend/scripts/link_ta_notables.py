"""Create knowledge graph edge: Twisted Amulet -> provides -> Instilled Notables."""
import sys, json
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.models.knowledge_graph import KbEntity, KbEdge

db = SessionLocal()

ta = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Twisted Amulet%")
).first()
cn = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Instilled Notables%")
).first()

if not ta: print("TA NOT FOUND"); exit()
if not cn: print("CN NOT FOUND"); exit()

print(f"TA id={ta.id}, CN id={cn.id}")

# Find or create entities
for chunk, name, etype in [
    (ta, "Twisted Amulet", "item"),
    (cn, "Instilled Notables", "passive"),
]:
    ent = db.query(KbEntity).filter(KbEntity.entity_key == name).first()
    if not ent:
        ent = KbEntity(entity_key=name, entity_type=etype, name_en=name, chunk_id=chunk.id)
        db.add(ent)
        db.flush()
    print(f"  Entity: {ent.id} {name}")

ta_ent = db.query(KbEntity).filter(KbEntity.entity_key == "Twisted Amulet").first()
cn_ent = db.query(KbEntity).filter(KbEntity.entity_key == "Instilled Notables").first()

edge = db.query(KbEdge).filter(
    KbEdge.src_entity_id == ta_ent.id,
    KbEdge.dst_entity_id == cn_ent.id,
).first()
if not edge:
    edge = KbEdge(
        src_entity_id=ta_ent.id,
        dst_entity_id=cn_ent.id,
        relation="provides",
        weight=2.0,
        source_chunk_id=ta.id,
    )
    db.add(edge)
    db.commit()
    print("Edge created!")
else:
    print("Edge exists")
db.close()
