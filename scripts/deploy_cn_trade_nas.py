"""Deploy cursor/cn-trade-realm branch to NAS and rebuild services."""
import io
import sys
import time

import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST, PORT, USER, PASS = "192.168.110.26", 2212, "skc", "SKChaidao@123"
DOCKER = "/usr/local/bin/docker"
ROOT = "/volume1/docker/PoE2LI"
BRANCH = "cursor/cn-trade-realm"


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 600) -> tuple[int, str, str]:
    print(f"\n>>> {cmd[:120]}{'...' if len(cmd) > 120 else ''}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out[-4000:] if len(out) > 4000 else out)
    if err:
        print("STDERR:", err[-2000:] if len(err) > 2000 else err)
    return code, out, err


def main() -> None:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, PORT, USER, PASS, timeout=15)

    cmds = [
        f"cd {ROOT} && git fetch origin",
        f"cd {ROOT} && git checkout -f {BRANCH} && git reset --hard origin/{BRANCH}",
        f"cd {ROOT} && {DOCKER} compose build backend frontend",
        f"cd {ROOT} && {DOCKER} compose up -d backend frontend",
        f"{DOCKER} exec poe2li-backend python -c 'from app.services.trade_realm import search_api_url; print(search_api_url(\"cn\"))'",
    ]
    for cmd in cmds:
        code, _, _ = run(client, cmd, timeout=900)
        if code != 0:
            print(f"FAILED exit={code}")
            client.close()
            sys.exit(code)

    client.close()
    print("\nDeploy OK. Set TRADE_CN_POESESSID in NAS .env then: docker compose up -d backend")


if __name__ == "__main__":
    main()
