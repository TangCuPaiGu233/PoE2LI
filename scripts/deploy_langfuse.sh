#!/bin/bash
# Deploy Langfuse on NAS - run from /volume1/docker/PoE2LI
set -e
D="/usr/local/bin/docker"
DC="$D compose"
cd /volume1/docker/PoE2LI

echo "=== Pulling images ==="
$D pull clickhouse/clickhouse-server:24
$D pull langfuse/langfuse:3
echo "=== Images ready ==="

echo "=== Starting ClickHouse ==="
$DC up -d langfuse-clickhouse
echo "Waiting for ClickHouse..."
for i in $(seq 1 30); do
    if $D exec poe2li-langfuse-clickhouse clickhouse-client -u langfuse --password langfuse_secret -q "SELECT 1" 2>/dev/null; then
        echo "ClickHouse healthy"
        break
    fi
    sleep 2
done

echo "=== Starting Langfuse ==="
$DC up -d langfuse
echo "Waiting for Langfuse..."
for i in $(seq 1 20); do
    if curl -sf http://localhost:3001/api/public/health 2>/dev/null; then
        echo "Langfuse healthy"
        break
    fi
    sleep 3
done

echo "=== Container status ==="
$D ps --filter "name=langfuse" --format "{{.Names}} {{.Status}}"
echo "=== DONE ==="
