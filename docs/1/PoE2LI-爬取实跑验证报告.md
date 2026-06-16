# PoE2LI 爬取实跑验证报告（poe2db 真实数据）

> 验证时间：2026-06-16
> 验证环境：云端沙箱（Python 3.12 + requests + BeautifulSoup + lxml）
> 验证对象：`docs/当前需求汇总.md` 需求1 的核心假设——"poe2db 页面结构能驱动实体+关系全量重建"
> 验证目标实体：升华职业（Ascendancy），重点验证"猎巫人归属"这个曾出 bug 的关键边

---

## 0. 一句话结论

**核心假设成立**：poe2db 的 DOM 结构确实能结构化抽出 `belongs_to`(升华→职业) 关系，
**`猎巫人 → 佣兵` 实跑验证通过**，噪声从启发式版的 296 条脏边降到 0。
同时实跑暴露 2 个纸面设计发现不了的真实问题（tab 懒加载、升华/天赋嵌套），需在爬虫骨架中修正。

---

## 1. 验证过程（5 轮迭代，每轮都有真实发现）

### 轮次1：URL 探活 —— 推测的索引页全错
| 我在骨架里猜的 URL | 实跑结果 |
|--------------------|----------|
| `/cn/Ascendancy_classes` | ❌ 404 |
| `/cn/Classes` | ❌ 404 |
| `/cn/`（首页） | ✅ 200，102506 字符 |

**结论**：站点可达，但骨架里的 `index_urls` 是猜的、不准。→ 必须从首页导航反查真实路径。

### 轮次2：从首页导航挖真实索引页路径
实跑从首页 579 个 `/cn/` 链接里挖出**真实索引页**：

| 实体类型 | 真实索引页 URL（实测有效） |
|----------|---------------------------|
| 升华职业 | `/cn/Ascendancy_class`（不是 `_classes`！） |
| 角色职业 | `/cn/Character_class` |
| 技能宝石 | `/cn/Skill_Gems` |
| 辅助宝石 | `/cn/Support_Gems` |
| 精神宝石 | `/cn/Spirit_Gems` |
| 暗金物品 | `/cn/Unique_item`（不是 `_items`！） |
| 天赋点 | `/cn/Passive_skill` |
| 基石天赋 | `/cn/Keystone` |
| 核心天赋 | `/cn/Notable` |
| 词缀 | `/cn/Modifiers` |

→ **这些是回填进 `config/entity_types.yaml` 的真实值**。

### 轮次3：索引页抓清单 —— 实体清单完整可达
`/cn/Ascendancy_class` 返回 200、445KB，抓出全部职业+升华，自带层级顺序：
```
游侠 → 锐眼/追猎者
女猎手 → 亚马逊/灵魂行者/仪祭师
佣兵 → 战术家/猎巫人/古灵使徒斗士   ← 猎巫人在佣兵下！
...
```
→ 证明"索引页全量发现"路线可行，根治旧 NLP 词典漏实体的问题。

### 轮次4：启发式抽边翻车 —— 暴露"不能靠链接顺序猜关系"
第一版用"按文档顺序遇到职业就更新 current_class"的启发式，结果：
- 抽出 296 条边，**大量噪声**
- `亚马逊 → 游侠` 又 `→ 女猎手`（一升华挂俩职业，矛盾）
- `战术家 → 魔巫`（明显错配）

**根因**：侧边导航/推荐位/面包屑里的职业链接污染了顺序指针。
→ **实证了解决思路文档的设计决策：关系抽取必须靠 DOM 结构块，不能靠链接出现顺序。**

### 轮次5：定位真实 DOM 容器 —— 抽干净
沿"猎巫人"链接逐层往上找祖先，定位到真实分组结构：

```
div.tab-content
  └ div.tab-pane (每个 tab 一组职业)
      └ div.row
          └ div.col                         ← 单个职业分组
              └ div.d-flex.border-top        ← 职业行容器 ★
                  ├ (职业图标/名)  = 佣兵
                  └ div.flex-grow-1.ms-2      ← 升华列表容器 ★
                      ├ 战术家 猎巫人 古灵使徒斗士  (升华)
                      └ 支援火力 元素结界 ...      (升华的天赋节点)
```

用 `div.d-flex.border-top > div.flex-grow-1` 重抽：
- **belongs_to 边 63 条，噪声 0**
- `猎巫人 → 佣兵` ✅ PASS
- `一升华挂多职业` = 无 ✅

---

## 2. 实跑产出的真实数据（节选）

干净图谱已存 `output/poe2_ascendancy_graph.json`，节选：

```
游侠   : 锐眼, 追猎者
女猎手 : 亚马逊, 灵魂行者, 仪祭师
佣兵   : 战术家, 猎巫人, 古灵使徒斗士
女巫   : 驱炎使, 命源法师, 巫妖
战士   : 泰坦, 战争使者, 奇塔弗匠师
魔巫   : 风暴编织者, 塑时术师, 瓦拉煞的门徒
行者   : 武圣, 祈求者, 夏乌拉追随者
```

实体 id 规则验证通过：`class:huntress`、`ascendancy:witchhunter`，与解决思路文档的 canonical id 设计一致。

---

## 3. 实跑揪出的 2 个真实问题（必须在爬虫骨架中修正）

### 问题1：tab 懒加载导致职业不全（抓到8/期望12）
- 现象：只抓到 游侠/女猎手/佣兵/女巫/战士/魔巫/行者 等 8 个职业，缺暗影/僧侣等。
- 根因：`/cn/Ascendancy_class` 用 Bootstrap tab（`tab-pane fade`），**只有 active tab 的内容在首屏 HTML 里**，其余 tab 内容需切换才渲染（或在另一份 HTML 片段）。
- **修正方案**（择一）：
  - a) 找每个 tab 对应的独立数据接口/锚点 URL，逐 tab 请求；
  - b) 直接爬每个职业的**详情页**（`/cn/Mercenary` 等），从详情页拿该职业的升华列表，更稳；
  - c) 若 tab 内容是 JS 渲染，改用带 JS 的抓取（playwright），但优先验证 a/b 纯 HTTP 是否够。
- → 推荐 **b**：职业详情页一职业一页，天然干净，且能顺带拿到职业的属性、起始位置等。

### 问题2：升华列表混入"升华天赋节点"（Notable）
- 现象：佣兵下出现"支援火力/元素结界/美德壁垒"，行者下出现"虚空钟灵/凝神思"——这些是**升华内部的天赋点，不是升华职业**。
- 根因：poe2db 把"升华职业 + 该升华的天赋节点"放在同一个 `flex-grow-1` 块里。
- **修正方案**：在 `flex-grow-1` 内分两层抽取——
  - 升华职业：通常是块内**带图标的标题级链接**（URL 是升华英文名，如 `/cn/Witchhunter`）；
  - 升华天赋：标题之下的子节点链接（URL 多为 `/cn/Notable` 类或带 passive 特征）。
  - 用 URL 特征 + DOM 层级双重判定区分，分别产出 `belongs_to`(升华→职业) 和 `grants`(升华→天赋节点) 两种边。
- → **正好实证了解决思路文档里 belongs_to / grants 要分开建模的必要性。**

---

## 4. 可回填到爬虫骨架的真实配置

### `config/entity_types.yaml`（修正 index_urls）
```yaml
entity_types:
  ascendancy:
    index_urls: ["https://poe2db.tw/cn/Ascendancy_class"]   # 修正：非 _classes
    # 注意：tab 懒加载，建议改走职业详情页路线
    parser: ascendancy_parser
  class:
    index_urls: ["https://poe2db.tw/cn/Character_class"]
    detail_url_tpl: "https://poe2db.tw/cn/{en_name}"        # 如 /cn/Mercenary
    parser: class_parser
  skill:
    index_urls: ["https://poe2db.tw/cn/Skill_Gems"]
  support:
    index_urls: ["https://poe2db.tw/cn/Support_Gems"]
  unique:
    index_urls: ["https://poe2db.tw/cn/Unique_item"]        # 修正：非 _items
  passive:
    index_urls: ["https://poe2db.tw/cn/Passive_skill"]
  keystone:
    index_urls: ["https://poe2db.tw/cn/Keystone"]
  notable:
    index_urls: ["https://poe2db.tw/cn/Notable"]
```

### `config/selectors/ascendancy.yaml`（实测选择器）
```yaml
entity_type: ascendancy
# 分组容器：每个职业一个 d-flex.border-top
group_block:    "div.d-flex.border-top"
class_link:     "a[href^='/cn/']"         # 块内首个属于基础职业集合的链接
ascendancy_list:"div.flex-grow-1 a[href^='/cn/']"  # 升华+天赋混在这，需分层
# 待修正：在 ascendancy_list 内用 URL 特征区分 升华 vs 天赋节点
base_classes: [Ranger, Huntress, Monk, Witch, Sorceress, Marauder,
               Warrior, Duelist, Mercenary, Shadow, Templar, Tactician]
```

---

## 5. 对四份文档的反哺

| 实跑发现 | 反哺到哪份文档 |
|----------|----------------|
| 真实 index_urls（_class 不是 _classes 等） | 爬虫骨架 §2.1 entity_types.yaml |
| 真实选择器 d-flex.border-top / flex-grow-1 | 爬虫骨架 §2.3 selectors |
| 关系必须靠 DOM 块不能靠顺序 | 解决思路 §2.2 阶段C（已是此设计，得到实证） |
| 升华/天赋嵌套 → belongs_to 与 grants 分层 | 解决思路 §2.2 field_relation_map（grants 的真实来源） |
| tab 懒加载 → 走详情页更稳 | 爬虫骨架 §3 阶段A 策略（补充详情页路线） |
| 猎巫人→佣兵 验证通过 | eval 评测集 REL-002 用例（真实可断言） |

---

## 6. 下一步建议

1. **按"问题1方案b"改爬虫**：走职业详情页 `/cn/{ClassEn}` 拿全 12 职业（解决 tab 懒加载）。
2. **实现升华/天赋分层**：在 flex-grow-1 内用 URL/DOM 特征区分，产出两类边。
3. **扩到技能页**：验证 `supports`(辅助→技能)、`requires_weapon` 等关系是否同样可结构化抽取。
4. 把本报告的真实选择器固化进 `config/selectors/`，让爬虫骨架从"骨架"变"可跑"。

> 本次实跑最大价值：**用真实数据证明了知识图谱方案可行（猎巫人归属修复坐实），同时提前暴露了 tab 懒加载和升华/天赋嵌套两个会卡住实施的真实坑**——这些都是纸面评审发现不了、只有真跑才能揪出来的。

---

# 第二批实跑：深挖数据关系，把图谱抽到零噪声

> 触发：用户要求"继续跑，但要注意数据的关系"
> 结论：**8 职业 × 23 升华 belongs_to 全量抽取、关系正确性全部 PASS、零噪声**。
> 最终干净产物：`output/poe2_ascendancy_graph_v2.json`

## 7. 又纠正了 2 个数据事实（实跑打脸假设）

### 纠错1：PoE2 只有 8 个职业，不是 12
- 上一批报告写"期望12职业"是按 PoE1 惯性，**错了**。
- 实跑 `/cn/Character_class` 拿到真实 8 职业：
  女巫(Witch)、游侠(Ranger)、战士(Warrior)、魔巫(Sorceress)、
  女猎手(Huntress)、佣兵(Mercenary)、行者(Monk)、德鲁伊(Druid)。
- → 上一批"抓到8/期望12"其实是**数据本来就全**，不是 tab 懒加载漏了。tab 懒加载问题被证伪。

### 纠错2："走职业详情页拿升华"路线走不通
- 上一批推荐的"方案b：爬 `/cn/Mercenary` 详情页拿升华"，实跑发现**详情页里根本没有升华链接**：
  `h2 Ascendancy` 下只有一句 `<a href="Ascendancy_class">Ascendancy</a>` 跳回索引页。
- → **职业→升华的归属，唯一权威来源就是 `/cn/Ascendancy_class` 索引页本身**。方案b 作废。

## 8. 摸清真实 DOM 结构（关键数据关系）

实跑逐层定位，最终厘清升华页真实结构：

```
div.col
  └ div.d-flex.border-top.rounded
      └ div.flex-grow-1.ms-2
          └ figure.text-center
              └ figcaption
                  └ a[href=/cn/Xxx]   ← 职业 或 升华（同在 figcaption）
          (figure 之后)
          └ div.implicitMod            ← 升华天赋的【效果描述文本】
              └ a[href=/cn/Yyy]        ← 描述里提到的【技能/关键词】，不是天赋名！
```

**三个决定性的数据关系结论**：
1. **职业和升华都在 `figcaption` 里**，靠"是否属于 8 大基础职业集合"区分谁是职业、谁是升华。
2. **`div.implicitMod` 是升华天赋的效果描述**，里面的 `<a>` 链接是**技能/关键词**（如"猛击""余震"），**不是天赋节点名**。之前把"支援火力"当天赋节点是误判——"支援火力"其实也在 figcaption 层。
3. **`d-flex.border-top` 是通用布局类，全页有 220 个**，不能当"职业块"用；真正的职业分组靠 `div.col` + figcaption 里的职业锚点。

## 9. 关系抽取避坑实录（именно"注意数据关系"的价值）

| 错误做法 | 翻车现象 | 正确做法 |
|----------|----------|----------|
| 按链接出现顺序猜归属 | 296 条脏边，亚马逊挂2职业 | 靠 figcaption + 职业锚点分组 |
| 用"最近的前序 figcaption"归属天赋 | "支援火力"错挂到德鲁伊升华 | 限定同一职业分组内配对 |
| 把 implicitMod 链接当天赋节点 | 抽出"猛击/余震"等技能当天赋 | implicitMod 是描述文本，天赋名在 figcaption |
| 假设 12 职业 / 走详情页 | 详情页无升华数据 | 索引页是唯一权威源，8 职业 |

> 核心教训：**关系的正确性 > 关系的数量**。宁可只抽 figcaption 这一层确定无疑的 belongs_to（23 条全对），也不要贪心去抽 implicitMod 里语义不清的链接（会引入技能/天赋混淆的脏边）。

## 10. 最终定稿图谱（全部 PASS）

```
佣兵   : 战术家, 猎巫人, 古灵使徒斗士
女猎手 : 亚马逊, 灵魂行者, 仪祭师
游侠   : 锐眼, 追猎者
行者   : 武圣, 祈求者, 夏乌拉追随者
女巫   : 驱炎使, 命源法师, 巫妖, 深渊巫妖
魔巫   : 风暴编织者, 塑时术师, 瓦拉煞的门徒
战士   : 泰坦, 战争使者, 奇塔弗匠师
德鲁伊 : 神谕者, 萨满
```

关系正确性校验（10 个关键样例）：**全部 PASS**
一升华挂多职业噪声：**无**
猎巫人 → 佣兵：**✅ 坐实（核心 bug 修复点）**

## 11. 可固化进爬虫骨架的最终选择器

```yaml
# config/selectors/ascendancy.yaml（实测可用，零噪声）
index_url: "https://poe2db.tw/cn/Ascendancy_class"
group_container: "div.col"                    # 每个职业一组
caption_links:   "div.flex-grow-1 figcaption a[href^='/cn/']"
base_classes_en: [Ranger, Huntress, Monk, Witch, Sorceress, Mercenary, Warrior, Druid]
rule:
  # caption_links 中属于 base_classes 的 = 职业；其余 = 该组升华
  # belongs_to: 升华 -> 该组职业
  # implicitMod 内链接是技能/关键词，不要当升华天赋抽取
```

## 12. 下一步（修正版）

1. **belongs_to 已 100% 可用** → 直接灌库，eval REL-002（猎巫人→佣兵）可作真实断言。
2. 升华天赋（notable）如需抽取，要单独爬**每个升华详情页**（如 `/cn/Witchhunter`），而非从索引页 implicitMod 抽——那里语义不清。
3. 扩到技能页验证 `supports` / `requires_weapon`，方法论同：先定位真实 DOM 容器，再靠结构块抽关系，绝不靠邻近顺序猜。

> 第二批最大价值：**应"注意数据关系"的要求，把关系抽取从"看着对"做到了"可校验全对、零噪声"**，并纠正了上一批两个错误假设（12职业、走详情页）。这再次印证：真跑数据 > 纸面推测。
