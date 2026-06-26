import sys
from pathlib import Path
sys.path.insert(0, str(Path('D:/PC_AI/Project/PoE2LI')))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import paramiko
from scripts.remote_ssh import connect_tencent

ROOT = "/opt/PoE2LI"
BRANCH = "cursor/cn-trade-realm"
COMPOSE = "docker compose -f docker-compose.yml -f docker-compose.tencent.yml"
TENCENT_BUNDLE_PATH = f"{ROOT}/poe2li-tencent-bundle.bundle"
TARGET_REF = "ca88793"


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


print("Verifying bundle on Tencent...")
tencent = connect_tencent()
try:
    run(tencent, f"cd {ROOT} && git bundle list-heads {TENCENT_BUNDLE_PATH}")
    run(tencent, f"cd {ROOT} && git bundle unbundle {TENCENT_BUNDLE_PATH}")
    run(tencent, f"cd {ROOT} && git checkout {BRANCH}")
    run(tencent, f"cd {ROOT} && git reset --hard {TARGET_REF}")

    print("Building and deploying...")
    run(tencent, f"cd {ROOT}; {COMPOSE} build backend frontend", timeout=3600)
    run(tencent, f"cd {ROOT}; {COMPOSE} up -d postgres redis backend frontend", timeout=600)

    print("Applying memory limits...")
    mem_limits = {
        "poe2li-postgres": "512m",
        "poe2li-redis": "128m",
        "poe2li-backend": "1536m",
        "poe2li-frontend": "384m",
    }
    for ctr, mem in mem_limits.items():
        run(tencent, f"docker update --memory={mem} --memory-swap={mem} {ctr}", timeout=30)

    print("Running health checks...")
    import time
    for attempt in range(1, 31):
        _, out8000, _ = run(tencent, "curl -sf -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health", timeout=30)
        _, out3000, _ = run(tencent, "curl -sf -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/", timeout=30)
        print(f"Health attempt {attempt}: backend={out8000.strip()} frontend={out3000.strip()}")
        if "200" in out8000 and ("200" in out3000 or "304" in out3000):
            print("Health checks passed.")
            break
        time.sleep(5)
    else:
        raise RuntimeError("Health checks failed")

    print("\n" + "=" * 60)
    print(f"Deploy OK: http://159.75.231.110:3000/chat")
    print("=" * 60)
finally:
    tencent.close()
