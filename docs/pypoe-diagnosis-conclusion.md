# PyPoE 诊断结论

> 诊断人：人间草木（CEO，因远岫停滞，自行验证）
> 时间：项目时间 第 8 天
> 环境：Python 3.12, PyPoE 1.0.0a0

## 一、环境验证结论

| 模块 | 状态 |
|------|------|
| `PyPoE.poe.file.ggpk.GGPKFile` | ✅ 可导入 |
| `PyPoE.poe.file.dat.DatFile` | ✅ 可导入 |
| `PyPoE.poe.file.bundle.Index` | ✅ 可导入 |
| `PyPoE.poe.file.specification.load` | ✅ 可导入 |
| `PyPoE.poe.file.specification.constants` | ✅ 可导入 |

**结论：PyPoE 在当前环境（Python 3.12）完全可用。**

## 二、GGPK 文件位置

```
C:\Program Files (x86)\Grinding Gear Games\Path of Exile 2 - poe2_production\Content.ggpk
大小：~160GB
```

即 `export_en_tc.py` 中的 `DEFAULT_GGPK` 路径。

## 三、对 TC 数据路线的建议

PyPoE 可正常使用，所以 TC 数据维护有以下选择：

### 方案 A：PyPoE 增量导出（推荐长期）
- `export_en_tc.py --tables <表名>` 可以按表导出
- 当 PoE2 更新时，用 PyPoE 重新导出 TC 子集即可
- 不需要手动维护 SC→TC 映射

### 方案 B：SC→TC 补齐（当前已完成，推荐先合入）
- 守夜已完成 356 文件补齐并通过 validate
- `fill_tc_from_sc.py` 脚本可用
- 建议**先合入 A010**，后续 PyPoE 导出作为增量维护手段

### 最终推荐
**先合入 A010（SC→TC 补齐），后续 Phase 2 将 PyPoE 增量导出集成到数据管道中。** 两者不冲突——SC→TC 是基线补齐，PyPoE 是增量更新。

## 四、对 Step 1B/C 的影响

PyPoE 诊断与 Step 1B (Planner Pydantic) 和 Step 1C (Fallback 改进) 正交，不阻塞。远岫可直接 dispatch 织墨执行。
