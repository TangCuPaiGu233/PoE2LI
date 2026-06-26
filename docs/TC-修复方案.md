# TC 繁体中文数据缺失诊断与修复方案

> 状态：初稿  
> 责任人：拾遗（数据工程师）  
> 关联 Sprint：Sprint 1 — 数据评估轨道  
> 依据：`assessments/data-ops-assessment.md`、`backend/scripts/ggpk/export_en_tc.py`

---

## 一、现状速览

| 目录 | 文件数 | 总大小 | 完整性 |
|------|--------|--------|--------|
| `backend/data/poe2_data/en/` | 356 | ~199 MB | ✅ 基准 |
| `backend/data/poe2_data/sc/` | 356 | ~199 MB | ✅ 完整 |
| `backend/data/poe2_data/tc/` | **102** | **~81 MB** | ❌ 缺失 254 个文件 |

**结论**：TC 目录仅有 EN 完整集的 28.6%，已造成繁体用户核心功能不可用。

---

## 二、缺失范围分析

### 2.1 核心缺失表（按影响分级）

| 等级 | 表名 | 影响说明 |
|:----:|------|----------|
| P0 | `Mods.json` | 所有词缀/词条定义缺失，AI 繁体问答、交易 stat 映射大面积失效 |
| P0 | `Stats.json` | 属性/状态定义缺失，检索与展示失效 |
| P0 | `PassiveSkills.json` | 天赋树数据缺失，天赋查询失效 |
| P0 | `BaseItemTypes.json` | 基础物品类型识别失效 |
| P0 | `GrantedEffects.json` / `GrantedEffectsPerLevel.json` | 技能效果与等级数据缺失，技能百科失效 |
| P0 | `ActiveSkills.json` | 主动技能数据缺失 |
| P0 | `ItemVisualIdentity.json` | 物品图标映射缺失，物品展示异常 |
| P1 | `MonsterVarieties.json` / `MonsterResistances.json` | 怪物数据缺失 |
| P1 | `CurrencyItems.json` / `Words.json` / `WorldAreas.json` | 通货/词汇/地区缺失 |
| P2 | 其余 200+ 小表 | 边缘功能降级，非阻塞 |

### 2.2 缺失类型判断

当前证据支持两种可能并存：

1. **导出未覆盖**：`export_en_tc.py` 的 `ALL_TABLES` / `LANG_PREFIXES` 过滤逻辑或 PyPoE spec 版本导致部分表在 TC 路径下根本未写出。
2. **客户端侧翻译缺失**：GGPK 中 TC override 目录本身缺少某些 `.datc64` 文件，即国际客户端繁体汉化不完整。

需要白盒验证后才能确定各自占比。

---

## 三、根因定位步骤

1. 在 `export_en_tc.py` 中增加 TC 导出诊断输出：
   - `en_paths` / `tc_paths` 数量对比
   - 逐表打印 `EN:xx / TC:xx` 或 `SKIP`
   - 记录 PyPoE `parse_dat` 异常表名
2. 对比 `ALL_TABLES` 与 GGPK 中实际存在的 TC 文件列表，确认是“脚本没写”还是“客户端没给”。
3. 若客户端确实无翻译，则确定“EN 为底 + SC/社区映射兜底”的降级边界。

---

## 四、修复方案

### 4.1 短期（Sprint 1）

- **修复导出脚本**：修正 `export_en_tc.py` 的 TC 路径发现逻辑，确保能写出所有客户端提供的 TC override。
- **补跑 TC 导出**：在 NAS 开发环境重新执行 TC 导出，生成完整 `tc/` 目录。
- **post-export 校验脚本**：补一套极简校验，断言：
  - `tc/` 文件数 ≥ EN 核心表数量
  - P0 表非空且行数 > 0
  - TC 行数 / EN 行数比例不低于阈值（如 0.5，避免静默缺省）

### 4.2 中期（Sprint 2）

- **入库侧断言**：`import_game_data.py` 对核心表增加 TC 缺失告警，不再静默缺省。
- **自动化校验接入 CI**：数据更新后自动比对三语文件数与关键字段存在率。
- **TC 缺失兜底策略**：若客户端确实缺少翻译，评估是否可从 SC / 社区资源做映射补充；如不可行，则在 RAG / tooltip 侧做显式降级提示。

---

## 五、依赖与工时预估

| 步骤 | 依赖 | 预估工时 |
|------|------|----------|
| 导出脚本 debug + 修复 | 无 | ~0.5d |
| 补跑 TC 导出 + 校验 | 有国际客户端 GGPK 可访问 | ~0.5d |
| post-export 校验脚本 | 无 | ~0.25d |
| 入库侧断言增强 | 无 | ~0.25d |
| CI 校验接入 | 暮鼓测试基建就绪后 | ~0.5d |
| TC 兜底策略评估 | 需产品确认降级边界 | ~0.5d |

**Sprint 1 内可完成**：导出修复 + 补跑 + 校验脚本 + 入库断言。

---

## 六、验收标准

- `backend/data/poe2_data/tc/` 核心表文件完整（P0 表 100% 覆盖）
- 补跑后 `tc/` 文件数达到与 EN 一致（或明确记录客户端侧真实缺失项）
- 校验脚本可执行并通过
- `import_game_data.py` 对 TC 缺失核心表产生显式告警而非静默缺省

---

*文档维护：拾遗 | 创建时间：项目时间 第 1 天*
