# TC 修复 — NAS 执行清单

> 给织墨/朝露直接照着跑  
> 环境：NAS `192.168.110.26:2212`，项目路径 `/volume1/docker/PoE2LI`

---

## 1. 前置条件

| 项 | 要求 | 说明 |
|----|------|------|
| Python | 3.10+ | NAS Docker 容器内已有 |
| PyPoE | 最新版 | `pip install PyPoE` |
| GGPK | 国际客户端 `Content.ggpk` | 需有 PoE2 安装，路径见下 |
| WeGame Bundles2 | 国服客户端 `Bundles2/` | 仅用于 SC 导出，TC 修复不需要 |

**GGPK 常见路径**（Windows）：
```
C:\Program Files (x86)\Grinding Gear Games\Path of Exile 2 - poe2_production\Content.ggpk
```

若 NAS 上无 PoE2 安装，需从某台 Windows 机器把 `Content.ggpk` 拷贝到 NAS 可访问路径，例如 `/volume1/docker/PoE2LI/data/Content.ggpk`。

---

## 2. 执行步骤

### Step 1：进入 NAS 容器

```bash
ssh -p 2212 skc@192.168.110.26
/usr/local/bin/docker exec -it poe2li-backend bash
cd /app
```

### Step 2：确认 PyPoE 已安装

```bash
python -c "from PyPoE.poe.file.ggpk import GGPKFile; print('PyPoE OK')"
```

若报错：
```bash
pip install PyPoE
```

### Step 3：备份现有 TC 数据

```bash
mkdir -p /app/data/poe2_data/backup
cp -r /app/data/poe2_data/tc /app/data/poe2_data/backup/tc-$(date +%Y%m%d)
```

### Step 4：执行 TC 导出（带 debug 输出）

```bash
python backend/scripts/ggpk/export_en_tc.py \
  --ggpk "/app/data/Content.ggpk" \
  --output /app/data/poe2_data
```

若 GGPK 在 NAS 其他路径，替换 `--ggpk` 值。

**期望输出**：
- 末尾打印 `EN: xx tables, xx records` 和 `TC: xx tables, xx records`
- 若存在 TC 缺失，会打印 `WARNING: xx tables missing in TC bundle` + 逐表 `MISSING TC: xxx`

### Step 5：运行 TC 校验脚本

```bash
python backend/scripts/verify_tc_export.py \
  --data-dir /app/data/poe2_data \
  --min-ratio 0.5
```

**期望输出**：
- `FAIL: 0` 且退出码为 0
- 若仍有缺失，会打印 `FAIL xxx: en=xx tc=xx ratio=xx`

### Step 6：入库断言验证（可选，仅需 PostgreSQL 连接）

```bash
python backend/scripts/import_game_data.py \
  --data-dir /app/data/poe2_data \
  --dry-run
```

**期望输出**：
- 每张表末尾打印 `TC OK xxx: xx/xx = 0.xx`
- P0 表若 TC 覆盖率低于 20%，会打印 `WARN  xxx: TC coverage low (xx/xx = 0.xx)`

---

## 3. 期望产出

| 文件 | 说明 |
|------|------|
| `backend/data/poe2_data/tc/*.json` | 补全后的 TC 数据文件 |
| 容器日志 | 含 TC 缺失 debug 信息 |
| 校验脚本输出 | 可截图或保存为日志 |

---

## 4. 异常处理

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| `ERROR: Could not find Bundles2/_.index.bin` | GGPK 路径错误或文件损坏 | 确认 `--ggpk` 指向有效 `Content.ggpk` |
| `EN: 356 tables, TC: 102 tables` 无变化 | TC 客户端侧确实无翻译 | 记录缺失表名，进入兜底策略评估 |
| PyPoE 解析异常 `parse_dat` 失败 | PyPoE spec 版本不匹配 | 升级 PyPoE：`pip install --upgrade PyPoE` |
| 校验脚本 `FAIL` | TC 行数不足或关键字段缺失 | 查看具体表名，判断是导出问题还是客户端缺失 |
| Docker 内存不足 | 566MB game_relations + 导出过程吃内存 | 临时调大容器 mem_limit 或分批导出 |

---

## 5. 完成后

将以下信息同步给拾遗：
1. 导出日志（含 `EN:xx / TC:xx` 和 `WARNING` 行）
2. 校验脚本输出
3. 若仍有缺失，提供缺失表名清单

拾遗会据此决定是否需要进入 TC 兜底策略评估。

---

*清单维护：拾遗 | 创建时间：项目时间 第 3 天*
