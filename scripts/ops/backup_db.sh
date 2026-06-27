#!/usr/bin/env bash
# =============================================================================
# PoE2LI — PostgreSQL 数据库备份脚本
# =============================================================================
# 适用环境：
#   - NAS Docker Compose（默认）
#   - 腾讯云 Docker Compose（通过 COMPOSE_FILE 指定 override）
#
# 前置条件：
#   - 已安装 docker / docker compose（NAS 路径：/usr/local/bin/docker）
#   - 脚本所在目录有写权限，用于存放备份文件
#
# 使用方式：
#   ./scripts/ops/backup_db.sh
#   BACKUP_DIR=/opt/backups ./scripts/ops/backup_db.sh
#   RETENTION_DAYS=14 ./scripts/ops/backup_db.sh
#
# 定时任务示例（NAS crontab -e）：
#   0 2 * * * /volume1/docker/PoE2LI/scripts/ops/backup_db.sh >> /volume1/docker/PoE2LI/data/backup.log 2>&1
# =============================================================================

set -euo pipefail

# -------------------------- 可配置参数 --------------------------
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
CONTAINER_NAME="${CONTAINER_NAME:-poe2li-postgres}"
DB_USER="${DB_USER:-poe2li}"
DB_NAME="${DB_NAME:-poe2li}"
BACKUP_DIR="${BACKUP_DIR:-$(pwd)/data/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_PREFIX="poe2li_pg_dump"
# ----------------------------------------------------------------

# 颜色输出（可选）
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# -------------------------- 检查依赖 --------------------------
if ! command -v docker &>/dev/null; then
    log_error "docker 未安装或不在 PATH 中"
    exit 1
fi

# NAS 特殊处理：docker 不在默认 PATH
if [ -f /usr/local/bin/docker ] && ! docker compose version &>/dev/null; then
    export PATH="/usr/local/bin:$PATH"
fi

if ! docker compose version &>/dev/null; then
    log_error "docker compose 不可用"
    exit 1
fi

# -------------------------- 创建备份目录 --------------------------
mkdir -p "${BACKUP_DIR}"

# -------------------------- 检查容器状态 --------------------------
if ! docker compose -f "${COMPOSE_FILE}" ps --format "{{.Name}} {{.Status}}" | grep -q "^${CONTAINER_NAME}"; then
    log_error "容器 ${CONTAINER_NAME} 未运行，请先启动 Docker Compose"
    exit 1
fi

# -------------------------- 执行备份 --------------------------
BACKUP_FILE="${BACKUP_DIR}/${BACKUP_PREFIX}_${TIMESTAMP}.dump"
log_info "开始备份: ${CONTAINER_NAME} → ${BACKUP_FILE}"

if docker compose -f "${COMPOSE_FILE}" exec -T "${CONTAINER_NAME}" \
    pg_dump -U "${DB_USER}" -d "${DB_NAME}" \
    --no-owner --no-acl -Fc -f "/tmp/${BACKUP_PREFIX}_${TIMESTAMP}.dump"; then
    log_info "pg_dump 完成"
else
    log_error "pg_dump 失败"
    exit 1
fi

# 从容器复制到宿主机
docker compose -f "${COMPOSE_FILE}" cp \
    "${CONTAINER_NAME}:/tmp/${BACKUP_PREFIX}_${TIMESTAMP}.dump" \
    "${BACKUP_FILE}" || {
        log_error "备份文件复制失败"
        exit 1
    }

# 清理容器内临时文件
docker compose -f "${COMPOSE_FILE}" exec -T "${CONTAINER_NAME}" \
    rm -f "/tmp/${BACKUP_PREFIX}_${TIMESTAMP}.dump" || true

# -------------------------- 备份后校验 --------------------------
BACKUP_SIZE="$(stat -f%z "${BACKUP_FILE}" 2>/dev/null || stat -c%s "${BACKUP_FILE}" 2>/dev/null || echo 0)"
if [ "${BACKUP_SIZE}" -lt 1024 ]; then
    log_warn "备份文件异常小 (${BACKUP_SIZE} bytes)，请检查数据库是否为空"
fi

log_info "备份完成: ${BACKUP_FILE} (${BACKUP_SIZE} bytes)"

# -------------------------- 清理过期备份 --------------------------
log_info "清理 ${RETENTION_DAYS} 天前的旧备份..."
find "${BACKUP_DIR}" -name "${BACKUP_PREFIX}_*.dump" -type f -mtime +${RETENTION_DAYS} -delete 2>/dev/null || true

# -------------------------- 备份清单 --------------------------
log_info "当前备份文件:"
ls -lh "${BACKUP_DIR}/${BACKUP_PREFIX}_"*.dump 2>/dev/null || log_warn "无备份文件"

# -------------------------- 完整性校验说明 --------------------------
# 推荐恢复验证命令：
#   docker compose -f docker-compose.yml exec -T postgres \
#     pg_restore -U poe2li -d poe2li_test --clean --if-exists < backup_file.dump
#   pg_restore -l backup_file.dump | head  # 查看备份内容列表

exit 0
