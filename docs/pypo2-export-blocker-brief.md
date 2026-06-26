# PyPoE TC 导出阻塞简报

> 状态：待远岫/后端接手  
> 创建人：守夜  
> 创建时间：项目时间 第 0 天 22:xx

## 一、现象

- `backend/scripts/ggpk/export_en_tc.py --tables GrantedEffects ...` 持续输出：
  - `WARNING: 5 requested tables not found in EN bundle: UNKNOWN EN: GrantedEffects ...`
  - 最终 `SKIP ... not found`，EN/TC 均 0 表导出
- 但**手工检索 GGPK index** 明确存在：
  - `data/balance/grantedeffects.datc64`
  - `data/balance/stats.datc64`
  - `data/balance/skillgems.datc64`
  - 等 P0 路径

## 二、已排除项

1. **GGPK 路径错误** — 已确认 160 GB 文件存在，`GGPKFile.read()` 成功
2. **Bundle index 未加载** — `Bundles2/_.index.bin` 读取成功，`Index` 对象正常
3. **bundle 读取失败** — 已补 `bundle_nodes` 回退逻辑，手工验证 `extract_file()` 可返回正确 raw bytes
4. **表名后缀问题** — 已增加 `.dat` 自动补全，`--tables GrantedEffects` 可正常转为 `GrantedEffects.dat`
5. **EN/TC 路径切片 bug** — 已修正 `parts[2]` 索引逻辑，`en_paths`/`tc_paths` 数量恢复正常

## 三、根因假设

### 假设 A：`export_en_tc.py` 的 `unknown` 过滤逻辑误杀

- 证据：`unknown` 列表生成逻辑为 `key not in en_paths`
- 矛盾：`[DEBUG] P0 probe` 显示 `en=True`，即 `key in en_paths` 为真
- 结论：**已基本排除**。调试输出与 UNKNOWN 矛盾，问题可能在后续循环或参数传递。

### 假设 B：`args.tables` / `tables` 变量在循环中被修改

- 证据：脚本在 `unknown` 分支有 `tables = [t for t in tables if t not in unknown]`
- 风险：若 `unknown` 非空，`tables` 被置空，后续 `for tn in tables` 不执行
- 当前状态：P0  probe 显示 `unknown` 仍包含这些表，故 `tables` 被清空 → 0 表导出
- 结论：**高度可疑**。需打印 `unknown` 内容与 `tables` 被修改后的值

### 假设 C：PyPoE `Index.get_file_record()` 对某些 path 表现异常

- 证据：手工调用 `idx.get_file_record("data/balance/stats.datc64")` 成功，但脚本内可能因大小写/编码差异失败
- 验证：未在脚本内打印 `fr` 对象，无法确认
- 结论：**待验证**。可在 `extract_file()` 内增加 path/type debug

### 假设 D：TC bundle 打包方式变化

- 证据：`EN paths: 1019, TC paths: 215`，TC 路径数显著偏低
- 可能：国际客户端新版本将部分 TC 数据合并到通用 bundle，或 TC override 打包路径变化
- 结论：**可能为真**，但无法解释为何 EN 侧也 `not found`

## 四、排查细节记录

### 4.1 环境

- GGPK 路径：`C:\Program Files (x86)\Grinding Gear Games\Path of Exile 2 - poe2_production\Content.ggpk`
- GGPK 大小：`160,295,499,787 bytes` (~160 GB)
- PyPoE：已安装（导入 `GGPKFile/Index/DatFile/specification` 正常）

### 4.2 关键输出片段

```
[1] Loading GGPK: ...
    EN paths: 1019, TC paths: 215
[DEBUG] P0 probe:
  GrantedEffects.dat: en=True, tc=False, en_path=data/balance/grantedeffects.datc64, tc_path=None
        extract_file EN raw=3019140
[2] Exporting 5 tables...
  SKIP  GrantedEffects.dat: not found
```

矛盾点：P0 probe 显示 `en=True`，但后续仍 SKIP。

### 4.3 可疑代码段

```python
unknown = []
for tn in tables:
    key = tn.replace(".dat", ".datc64").lower()
    if key not in en_paths:
        unknown.append(tn)
if unknown:
    tables = [t for t in tables if t not in unknown]
```

若 `unknown` 非空，`tables` 被清空，后续导出循环为空。

## 五、建议接手步骤

1. **打印 `unknown` 与 `tables`** — 在 `if unknown:` 分支增加 `print(f"unknown={unknown}, tables after filter={tables}")`
2. **单表最小复现** — 只传 `--tables GrantedEffects`，观察是否仍进入 `unknown`
3. **检查 `extract_file()` 返回值** — 在 `en_raw = extract_file(...)` 后打印 `raw is None`
4. **对比 PyPoE 版本** — 确认 `spec_constants.VERSION.POE2` 与客户端版本匹配
5. **TC bundle 路径审计** — 枚举所有 `traditional chinese/*.datc64`，确认是否真的有 215 个，还是索引重复/损坏

## 六、环境详情

- Python：3.12（`C:\Users\99744\AppData\Local\Programs\Python\Python312\Lib\site-packages\PyPoE`）
- PyPoE 版本：`1.0.0a0`
- PyPoE POE2 spec version：`16`
- 关键导入正常：`GGPKFile`, `Index`, `DatFile`, `specification.load`, `spec_constants.VERSION.POE2`

## 七、待决策

- 是否由远岫评估 PyPoE 升级/替换方案？
- 是否接受临时用 SC 数据 + EN fallback 支撑 TC 场景？
- 是否需要在 NAS 环境手动跑 `extract_sc.py` 验证 SC 流程是否正常？
