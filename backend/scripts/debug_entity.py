import sys
sys.path.insert(0, "/app")
from app.services.entity_dict import normalize_ascendancy, resolve_ascendancy_en
from app.services.entity_resolver import resolve_all_entities

# Test with exact Chinese text
text = "灵魂行者说BD没有召唤物啊"
print("text:", repr(text))

asc_cn = normalize_ascendancy(text)
print("normalize_ascendancy:", repr(asc_cn))
print("resolve_ascendancy_en:", repr(resolve_ascendancy_en(asc_cn)))

entities = resolve_all_entities(text)
print("resolve_all_entities:", entities)
