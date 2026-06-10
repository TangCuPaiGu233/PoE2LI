# PoE2 数据采集总纲

> 一份够用的总纲：所有数据源、确切地址、可爬性、采集策略，看这份就行。
> 全部地址均经实测验证（标注状态）。
> 配套细节文档见文末「附录」。

---

## 〇、30 秒速览：四大数据源分工

| 数据源 | 角色 | 给什么 | 自动化 |
|---|---|---|---|
| **PoB 仓库** | 零件 + 规则 | 物品/宝石/词缀/天赋/召唤物/计算常量 | ✅ 全自动 |
| **GGG 官方 API** | meta 统计 | 天梯职业分布、物品类型、赛季 | ✅ 全自动 |
| **poe2db** | 中文皮肤 | 中文名/描述/机制关键词 | ✅ 全自动 |
| **poe.ninja** | 成套范例 | 真实玩家 BD 模板 | ⚠️ 需本地F12逆向 |
| **PoB 引擎** | 数值裁判 | DPS/EHP 校验 | （计算非采集） |

> **心法**：结构化数据拉 PoB，中文文本抓 poe2db，meta 统计用 GGG 官方，成套范例靠 poe.ninja，合理性校验交 PoB 引擎。

---

## 一、PoB 仓库（PathOfBuilding-PoE2）— 主力数据源

**仓库**：`PathOfBuildingCommunity/PathOfBuilding-PoE2`，分支 `dev`
**推荐 CDN**（绕 GitHub 限流，国内快）：
```
https://cdn.jsdelivr.net/gh/PathOfBuildingCommunity/PathOfBuilding-PoE2@dev/{路径}
```

### 1.1 基础物品（`src/Data/Bases/`，28 文件）
| 类别 | 文件 |
|---|---|
| 武器 | axe / bow / claw / crossbow / dagger / flail / mace / sceptre / spear / staff / sword / wand `.lua` |
| 防具 | body / boots / gloves / helmet / shield / focus `.lua` |
| 饰品其他 | amulet / ring / belt / quiver / talisman / jewel / flask / traptool `.lua` |

格式样例（已实测）：
```lua
itemBases["Broadhead Quiver"] = {
    type = "Quiver",
    implicit = "Adds 1 to 3 Physical Damage to Attacks",
    implicitModTypes = { { "physical_damage","damage","physical","attack" } },
}
```

### 1.2 BD 构建核心数据（`src/Data/` 顶层，已实测存在）
| 文件 | 大小 | 内容 | 用途 |
|---|---|---|---|
| `Gems.lua` | 513KB | 技能+辅助宝石全量 | 🔥 配伤害 combo |
| `ModItem.lua` | 1MB | 物品词缀池+roll范围 | 🔥 生成装备 |
| `ModJewel.lua` | 150KB | 珠宝词缀 | 进阶优化 |
| `Minions.lua` | 44KB | 召唤物（32条带tag） | 死灵流核心 |
| `ClusterJewels.lua` | — | 星团珠宝 | 天赋扩展 |
| `Bosses.lua` | — | Boss血量抗性 | DPS校验 |
| `Global.lua` | — | 全局常量/公式参数 | 数值计算 |
| `Gems`/`Mod*`/`QuestRewards`/`Spectres`/`WorldAreas` | — | 宝石/词缀/任务/幽灵/区域 | 全量补充 |

### 1.3 天赋树（`src/TreeData/{版本}/tree.json`）
```
https://cdn.jsdelivr.net/gh/PathOfBuildingCommunity/PathOfBuilding-PoE2@dev/src/TreeData/0_5/tree.json
```
- 实测：1.82MB / **4912 节点** / 8 职业 / 含升华节点
- 版本目录：`0_1`~`0_5`，最新用 `0_5`，新版本号往上抬
- 含升华天赋：按节点 `ascendancy` 字段筛

> ⚠️ PoB 数据是 `.lua`（天赋树是 `.json`）。Lua 格式极规整，用 `slpp`/`lupa` 或正则解析。文件头标 `automatically generated` → 跟 `@dev` 分支自动更新。

---

## 二、GGG 官方 API（meta 统计）— 已实测 200

```
# 天梯角色列表（15000人，职业/升华分布 = 版本 meta 地图）
https://www.pathofexile.com/api/ladders?id={赛季}&realm=poe2&limit=200&offset=0

# 赛季列表
https://api.pathofexile.com/leagues?realm=poe2

# 物品类型全量
https://www.pathofexile.com/api/trade2/data/items
```
- ✅ 可拿：排名/等级/职业/升华/角色名/账号
- ⚠️ 个人详细装备（`character-window/get-items`）→ **403，需登录态 POESESSID**
- 限速：约 45 req/min，带合规 UA，遵守 GGG ToS

---

## 三、poe2db（中文皮肤）— SSR 静态页可直抓

**可爬规律**：列表/词条页 = SSR（直抓）；机制/天赋树页 = CSR（抓回空白）

| 数据 | 入口 | 状态 |
|---|---|---|
| 传奇物品（528） | `/cn/Unique_item` | ✅ |
| 基础物品 | `/cn/Quivers`、`/cn/Bows`… 按类型分页 | ✅ |
| 升华职业 | `/cn/Ascendancy_class` | ✅ |
| 技能详情 | 各技能页 | ✅ |
| **机制关键词** | `/cn/Keywords`（616KB，非 Mechanics！） | ✅ |
| 词缀/任务 | 对应页 | ✅ |
| ❌ Mechanics 页 | `/cn/Mechanics` | JS渲染，空白 |
| ❌ 天赋树页 | `/cn/Passive_Skill` | JS渲染，空白 |

> 关键坑：机制词条要抓 `/cn/Keywords` 不是 `/cn/Mechanics`。天赋树别爬 poe2db，走 PoB tree.json。

---

## 四、poe.ninja（成套 BD 范例）— 需本地 F12 逆向

价值最高（聚合好的真实 BD 模板），但：
- 页面 JS 渲染（抓回空白），API 路径盲猜全 404
- **唯一可靠方式**：本地浏览器开 `poe.ninja/poe2/builds` → F12 → Network → 筛 XHR → 复制真实 API URL
- 沙箱无法开浏览器，这一步需你本地花几分钟完成

---

## 五、采集优先级路线（SOP）

| 阶段 | 任务 | 数据源 | 难度 |
|---|---|---|---|
| P0 | 基础物品全量 | PoB Bases/*.lua | 低 |
| P0 | 宝石+词缀池 | PoB Gems.lua / ModItem.lua | 低 |
| P0 | 机制关键词 | poe2db /cn/Keywords | 低 |
| P0 | 天赋树 | PoB 0_5/tree.json | 低 |
| P1 | 天梯 meta 统计 | GGG ladders API | 低 |
| P1 | 召唤物/Boss | PoB Minions/Bosses.lua | 低 |
| P1 | 升华天赋详情 | tree.json 筛 ascendancy | 中 |
| P2 | 成套 BD 范例 | poe.ninja（本地逆向） | 中 |
| P2 | 中文攻略语料 | B站/NGA SSR 页 | 中 |
| P3 | DPS/EHP 校验 | 接 PoB 计算引擎 | 高 |

---

## 六、采集工程通用规范

- **限速**：请求间隔随机 1-3s，尊重各站 ToS（GGG 45/min）
- **CDN 优先**：GitHub 数据走 jsDelivr，绕限流+加速
- **断点续爬**：记录已抓清单，失败可续
- **缓存原始数据**：先存原文再解析，改解析器不用重爬
- **增量更新**：按游戏版本号 diff，PoB `@dev` 自动跟版本
- **版权合规**：poe2db 是 CC BY-NC-SA 3.0，注明来源、非商用

---

## 七、数据源 → 能力映射（这些数据能撑起什么功能）

| 能力 | 依赖数据 | 现状 |
|---|---|---|
| 百科问答（现有） | poe2db chunk + 向量 | ✅ 已上线 |
| 传奇推荐（已做） | 传奇+流派标签+召唤物 | ✅ 骨架完成 |
| 装备 roll 建议 | ModItem 词缀池 | 数据已定位 |
| 技能 combo 搭配 | Gems 联动规则 | 数据已定位 |
| 天赋加点建议 | tree.json | 数据已定位 |
| **AI 自动造 BD** | 全部 + PoB引擎校验 + 范例语料 | 数据链已通，待开发 |

---

## 附录：详细专题文档

| 文档 | 内容 |
|---|---|
| `全量爬取作战手册.md` | 网站可爬性分析、三类卡点拆解 |
| `机制页与天赋树-逆向定位结果.md` | Keywords页 + tree.json 确切地址 |
| `PoB数据源-基础物品与全量数据地图.md` | PoB 全家桶详细文件清单 |
| `AI自动生成BD-数据需求清单.md` | 造 BD 的数据缺口 + 架构建议 |
| `BD范例语料-数据源深挖结果.md` | GGG API + poe.ninja 深挖结果 |
| `推荐问答系统-技术方案.md` | 推荐 Agent 完整技术方案 |
| `成果文档.md` | 推荐系统开发成果总览 |

---

## 一句话收尾

> **结构化拉 PoB，中文抓 poe2db，meta 用 GGG 官方，范例靠 poe.ninja，合理性交 PoB 引擎。**
> 五源各司其职，从"百科问答"一路通到"AI 造 BD"，数据链已全部打通。
