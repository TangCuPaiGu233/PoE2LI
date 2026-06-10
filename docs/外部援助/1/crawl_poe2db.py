"""poe2db 爬虫 v2：精准解析传奇物品 + 升华职业。

锚点（已验证）：
  - 传奇名: <span class="uniqueName">名字</span> <span class="uniqueTypeLine">类型</span>
  - 升华页: /cn/Ascendancy_class
"""
import json
import os
import re
import time
import urllib.request

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
OUT = "/workspace/output/recommend"
os.makedirs(OUT, exist_ok=True)


def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", errors="ignore"), r.status
        except Exception as e:
            print(f"  [retry {i+1}] {e}")
            time.sleep(1.5)
    return None, None


# ───────── 1. 传奇物品 ─────────
print("=== 抓取传奇物品 ===")
html, st = fetch("https://poe2db.tw/cn/Unique_item")
print(f"  status={st}, len={len(html or '')}")

uniques = []
seen = set()
# uniqueName + 可选 typeLine + href slug
pat = re.compile(
    r'href="(/cn/[^"]+)"[^>]*>\s*<span class="uniqueName">([^<]+)</span>'
    r'(?:\s*<span class="uniqueTypeLine">([^<]*)</span>)?'
)
for m in pat.finditer(html or ""):
    slug, name, base = m.group(1), m.group(2).strip(), (m.group(3) or "").strip()
    if name and name not in seen:
        seen.add(name)
        uniques.append({"name": name, "base_type": base, "slug": slug})

print(f"  ✅ 解析 {len(uniques)} 个传奇")
print("  样例:", [u["name"] for u in uniques[:12]])

# 给传奇打流派标签：扫描该传奇在页面中的词缀文本（用 name 定位附近文本）
# 简化：用关键词匹配判断传奇偏向哪个流派（minion/ignite/poison/lightning...）
ARCHE_KW = {
    "minion": ["召唤生物", "召唤物", "亡灵", "骷髅", "傀儡"],
    "ignite": ["点燃", "燃烧", "易燃", "火焰"],
    "poison": ["中毒", "混沌伤害"],
    "lightning": ["闪电", "感电", "触电"],
    "cold": ["冰霜", "冻结", "冰缓"],
    "physical": ["物理伤害", "流血", "晕眩"],
    "crit": ["暴击"],
}
plain = re.sub(r"<[^>]+>", " ", html or "")
for u in uniques:
    idx = plain.find(u["name"])
    block = plain[idx: idx + 300] if idx >= 0 else ""
    tags = [a for a, kws in ARCHE_KW.items() if any(k in block for k in kws)]
    u["archetypes"] = tags

with open(f"{OUT}/poe2db_uniques.json", "w", encoding="utf-8") as f:
    json.dump(uniques, f, ensure_ascii=False, indent=2)

# ───────── 2. 升华职业 ─────────
print("\n=== 抓取升华职业 ===")
asc_html, st = fetch("https://poe2db.tw/cn/Ascendancy_class")
print(f"  status={st}, len={len(asc_html or '')}")

ascendancies = []
if asc_html:
    # 升华详情页链接通常: href="/cn/XXX_ascendancy" 或 class 名含 Ascendancy
    # 先尝试抓导航/列表中的升华名（带链接的短中文）
    seen_a = set()
    for m in re.finditer(r'href="(/cn/[^"]*)"[^>]*>([^<]{2,8})</a>', asc_html):
        slug, name = m.group(1), m.group(2).strip()
        # 升华名启发式：2-6字中文，且 slug 含 ascendancy / class 相关
        if (2 <= len(name) <= 6 and re.match(r"^[\u4e00-\u9fa5]+$", name)
                and name not in seen_a
                and not any(x in name for x in ["职业", "天赋", "首页", "物品", "宝石", "词缀"])):
            seen_a.add(name)
            ascendancies.append({"name": name, "slug": slug})
    print(f"  ✅ 解析 {len(ascendancies)} 个升华候选")
    print("  样例:", [a["name"] for a in ascendancies[:20]])

with open(f"{OUT}/poe2db_ascendancies.json", "w", encoding="utf-8") as f:
    json.dump(ascendancies, f, ensure_ascii=False, indent=2)

# ───────── 汇总 ─────────
arche_stat = {}
for u in uniques:
    for a in u["archetypes"]:
        arche_stat[a] = arche_stat.get(a, 0) + 1
print(f"\n✅ 完成。传奇 {len(uniques)} 个，升华 {len(ascendancies)} 个")
print("  流派标签分布:", arche_stat)
print("  死灵(minion)传奇样例:",
      [u["name"] for u in uniques if "minion" in u["archetypes"]][:10])
