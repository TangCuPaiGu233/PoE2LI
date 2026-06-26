# TC 数据完整性校验报告

> 校验人：守夜  
> 时间：项目时间 第 5 天 17:43  
> 数据路径：`D:/PC_AI/Project/PoE2LI/backend/data/poe2_data`

## 一、文件数

| 目录 | 数量 |
|------|------|
| EN | 356 |
| SC | 356 |
| TC | 356 |

## 二、JSON 可解析性

- 坏 JSON：`0`
- 全部 356 个 TC JSON 文件均可正常 `json.load()`

## 三、P0 表覆盖

| 表名 | TC 状态 | 行数 |
|------|---------|------|
| GrantedEffects | exists | 8,339 |
| GrantedEffectsPerLevel | exists | 34,169 |
| ItemVisualIdentity | exists | 17,151 |
| Stats | exists | 27,013 |
| SkillGems | exists | 1,188 |

## 四、差异说明

- TC 相对 EN：无缺失
- 未发现结构性缺失

## 五、结论

**通过**。当前 TC 目录 356 个文件完整、P0 全覆盖、JSON 可解析，满足朝露 dispatch 的验收基线。
