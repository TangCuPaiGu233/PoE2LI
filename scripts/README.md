# Scripts layout

PoE2LI 脚本分三类：**部署**、**远程运维**、**数据/别名工具**。  
一次性 AI patch / probe 脚本已清理；长期可用的都收进下面目录。

## 部署（从本机执行）

| 脚本 | 用途 |
|------|------|
| [`deploy_nas.py`](../deploy_nas.py) | NAS 全量：`git reset origin/main` + compose build（含 chat UI 防回滚检查） |
| [`deploy_tencent.py`](deploy_tencent.py) | 腾讯云大版本发布；可选 `SYNC_NAS_DATA=1` 同步 KB |
| [`deploy_cn_trade_nas.py`](deploy_cn_trade_nas.py) | NAS 拉 `main` 并 rebuild backend+frontend（`NAS_GIT_REF` 可改分支） |

环境变量见 [`docs/ops/deployment.md`](../docs/ops/deployment.md)。

## NAS 远程运维 — `scripts/nas/`

需本机 `paramiko`；默认 SSH `192.168.110.26:2212`，可通过 `NAS_HOST` / `NAS_PASS` 等覆盖（见 [`remote_ssh.py`](remote_ssh.py)）。

| 脚本 | 用途 |
|------|------|
| `fetch_logs.py` | 拉 backend docker logs |
| `fetch_chat_audit.py` | 过滤 CHAT/trade 相关日志 → `scripts/out/nas_chat_audit.txt` |
| `verify_trade.py` | CN league / 猎首解析 / POESESSID 长度检查 |
| `restart_backend.py` | `git reset origin/main` + restart backend |
| `wiki_data_status.py` | wiki 图标爬取进度 |
| `run_wiki_icon_scrape.py` | 上传 scraper 并在容器内 resume |
| `kill_and_scrape_wiki.py` | 杀僵死 scraper 后重启 |
| `retry_wiki_icon_failures.py` | 重试 `failures.jsonl` |
| `deploy_icon_wiki.py` | 热更 icon 服务 + poe2db backfill + catalog |
| `hotfix_chat_images.py` | **应急**：只更 chat 图片 UI 并 rebuild frontend |
| `hotfix_backend.py` | **应急**：docker cp 未 push 的 backend 文件 |

```powershell
python scripts/nas/fetch_logs.py --tail 300
python scripts/nas/fetch_chat_audit.py
python scripts/nas/hotfix_backend.py   # 仅开发调试，优先走 git deploy
```

## 腾讯云运维 — `scripts/tencent/`

| 脚本 | 用途 |
|------|------|
| `health_check.py` | 容器 / 端口 / nginx 探测 |
| `fetch_logs.py` | 过滤 chat/trade 日志 → `scripts/out/tencent_logs.txt` |

## 数据 / 别名 — 本地或 NAS 容器内

| 脚本 | 运行位置 |
|------|----------|
| [`audit_cn_en_aliases.py`](audit_cn_en_aliases.py) | 本地：中英别名覆盖率审计 |
| [`backend/scripts/scrape_poe2wiki_icons.py`](../backend/scripts/scrape_poe2wiki_icons.py) | NAS 容器：wiki 图标批量下载 |
| [`backend/scripts/backfill_poe2db_icon_gaps.py`](../backend/scripts/backfill_poe2db_icon_gaps.py) | NAS 容器：poe2db 补图标 |
| [`backend/scripts/build_entity_catalog.py`](../backend/scripts/build_entity_catalog.py) | NAS 容器：生成 entity catalog |
| [`backend/scripts/fetch_trade_*_bilingual.py`](../backend/scripts/) | 本地：拉官方 trade stats/items 双语表 |

## 已删除（勿恢复）

以下属于 **一次性 patch 生成器 / 调试 probe**，功能已进 `main` 源码或测试，不应再保留：

- `backend/_p*.py`、`backend/scripts/_*.py` — 字符串替换 patch
- `scripts/_*.py` — 同上 + 重复 NAS 探针
- `frontend/scripts/*` — 前端 UI 一次性 patch
- `scripts/fix_*.py`、`scripts/patch_*.py` — 已合并进主代码

若需类似能力，改主代码 + pytest，或加正式的 `scripts/nas/` 运维脚本。
