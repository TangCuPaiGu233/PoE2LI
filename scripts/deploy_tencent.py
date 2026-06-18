#!/usr/bin/env python3
"""Deploy PoE2LI to Tencent cloud VM via SSH (paramiko)."""
from __future__ import annotations

import io
import os
import sys
import time

import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HOST = os.getenv("TENCENT_HOST", "159.75.231.110")
USER = os.getenv("TENCENT_USER", "root")
PORT = int(os.getenv("TENCENT_PORT", "22"))
PASS = os.getenv("TENCENT_SSH_PASS", "")
ROOT = os.getenv("TENCENT_ROOT", "/opt/PoE2LI")
BRANCH = os.getenv("TENCENT_BRANCH", "main")
REPO = "https://github.com/TangCuPaiGu233/PoE2LI.git"

NAS_HOST = "192.168.110.26"
NAS_PORT = 2212
NAS_USER = "skc"
NAS_PASS = "SKChaidao@123"
NAS_ENV_PATH = "/volume1/docker/PoE2LI/.env"

COMPOSE = "docker compose -f docker-compose.yml -f docker-compose.tencent.yml"
PROXY_PREFIXES = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


def strip_proxy_lines(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in PROXY_PREFIXES:
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def connect(host: str, port: int, user: str, password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port, user, password, timeout=30)
    return client


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 600, check: bool = True) -> tuple[int, str, str]:
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out.rstrip())
    if err:
        print(err.rstrip(), file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"Command failed (exit {code}): {cmd}")
    return code, out, err


def fetch_env_from_nas() -> str:
    print(f"Fetching .env from NAS {NAS_HOST}:{NAS_PORT} ...")
    nas = connect(NAS_HOST, NAS_PORT, NAS_USER, NAS_PASS)
    try:
        _, out, _ = run(nas, f"cat {NAS_ENV_PATH}", timeout=60)
        return strip_proxy_lines(out)
    finally:
        nas.close()


def upload_env(client: paramiko.SSHClient, content: str) -> None:
    run(client, f"mkdir -p {ROOT}")
    sftp = client.open_sftp()
    try:
        remote = f"{ROOT}/.env"
        with sftp.file(remote, "w") as f:
            f.write(content)
        run(client, f"chmod 600 {ROOT}/.env", timeout=30)
    finally:
        sftp.close()


def ensure_docker(client: paramiko.SSHClient) -> None:
    code, _, _ = run(client, "command -v docker", check=False)
    if code == 0:
        run(client, "docker compose version", check=False)
        return
    print("Docker not found; installing via dnf (OpenCloudOS/CentOS) ...")
    run(
        client,
        "dnf install -y docker docker-compose-plugin && systemctl enable docker && systemctl start docker",
        timeout=900,
    )


def ensure_repo(client: paramiko.SSHClient) -> None:
    run(client, f"mkdir -p {ROOT}")
    code, _, _ = run(client, f"test -d {ROOT}/.git", check=False)
    if code != 0:
        run(client, f"git clone {REPO} {ROOT}", timeout=600)
    run(client, f"cd {ROOT}; git fetch origin; git checkout {BRANCH}; git pull origin {BRANCH}", timeout=300)


def sync_nas_data(tencent: paramiko.SSHClient) -> None:
    print("SYNC_NAS_DATA=1: dumping NAS postgres and restoring on Tencent ...")
    nas = connect(NAS_HOST, NAS_PORT, NAS_USER, NAS_PASS)
    try:
        dump_cmd = (
            "/usr/local/bin/docker exec poe2li-postgres "
            "pg_dump -U poe2li -d poe2li --no-owner --no-acl -Fc"
        )
        print(f"NAS dump: {dump_cmd}")
        stdin, stdout, stderr = nas.exec_command(dump_cmd, timeout=3600)
        dump_bytes = stdout.read()
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise RuntimeError(f"NAS pg_dump failed (exit {code}): {err}")
        if not dump_bytes:
            raise RuntimeError("NAS pg_dump returned empty output")
        print(f"Dump size: {len(dump_bytes)} bytes")

        sftp = tencent.open_sftp()
        remote_dump = f"{ROOT}/nas_sync.dump"
        try:
            with sftp.file(remote_dump, "wb") as f:
                f.write(dump_bytes)
        finally:
            sftp.close()

        run(tencent, f"cd {ROOT}; {COMPOSE} up -d postgres", timeout=300)
        run(tencent, f"cd {ROOT}; {COMPOSE} exec -T postgres pg_isready -U poe2li -d poe2li", timeout=120)
        restore_cmd = (
            f"cd {ROOT}; cat {remote_dump} | "
            f"{COMPOSE} exec -T postgres pg_restore -U poe2li -d poe2li --clean --if-exists --no-owner --no-acl"
        )
        code, _, err = run(tencent, restore_cmd, timeout=3600, check=False)
        if code != 0:
            print(f"pg_restore exit {code}: {err}", file=sys.stderr)
        run(tencent, f"rm -f {remote_dump}", check=False)
    finally:
        nas.close()


def health_checks(client: paramiko.SSHClient) -> None:
    for attempt in range(1, 31):
        _, out8000, _ = run(
            client,
            "curl -sf -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health",
            timeout=30,
            check=False,
        )
        _, out3000, _ = run(
            client,
            "curl -sf -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/",
            timeout=30,
            check=False,
        )
        ok8000 = "200" in out8000
        ok3000 = "200" in out3000 or "304" in out3000
        print(f"Health attempt {attempt}: backend={out8000.strip()} frontend={out3000.strip()}")
        if ok8000 and ok3000:
            return
        time.sleep(5)
    raise RuntimeError("Health checks failed after 30 attempts (backend :8000, frontend :3000)")


def main() -> int:
    if not PASS:
        print("Set TENCENT_SSH_PASS (SSH password for Tencent VM).", file=sys.stderr)
        return 1

    env_content = fetch_env_from_nas()

    print(f"Connecting to Tencent {HOST}:{PORT} as {USER} ...")
    client = connect(HOST, PORT, USER, PASS)
    try:
        ensure_docker(client)
        ensure_repo(client)
        upload_env(client, env_content)

        run(client, f"cd {ROOT}; {COMPOSE} build backend frontend", timeout=3600)
        run(
            client,
            f"cd {ROOT}; {COMPOSE} up -d postgres redis backend frontend",
            timeout=600,
        )

        # Enforce memory limits — Docker Compose V2 ignores both mem_limit and
        # deploy.resources.limits.memory in non-swarm mode, so apply via docker update.
        _mem_limits = {
            "poe2li-postgres": "512m",
            "poe2li-redis": "128m",
            "poe2li-backend": "1228m",
            "poe2li-frontend": "384m",
        }
        for _ctr, _mem in _mem_limits.items():
            run(
                client,
                f"docker update --memory={_mem} --memory-swap={_mem} {_ctr}",
                timeout=30,
                check=False,
            )

        if os.getenv("SYNC_NAS_DATA", "").strip().lower() in ("1", "true", "yes", "y"):
            sync_nas_data(client)

        health_checks(client)

        url = f"http://{HOST}:3000/chat"
        print("\n" + "=" * 60)
        print(f"Deploy OK: {url}")
        print("Open Tencent Cloud security group / firewall for TCP port 3000 (and 8000 if needed).")
        print("=" * 60)
        return 0
    except Exception as exc:
        print(f"Deploy failed: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
