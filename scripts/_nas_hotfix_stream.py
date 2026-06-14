"""Hot-deploy chat_agent + trade_agent fixes to NAS backend container."""
import base64
import io
import sys

import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

NAS_HOST = "192.168.110.26"
NAS_PORT = 2212
NAS_USER = "skc"
NAS_PASS = "SKChaidao@123"

FILES = [
    ("backend/app/services/trade_agent.py", "/tmp/trade_agent.py"),
    ("backend/app/services/trade_concepts.py", "/tmp/trade_concepts.py"),
    ("backend/app/services/chat_tools.py", "/tmp/chat_tools.py"),
    ("backend/app/services/chat_agent.py", "/tmp/chat_agent.py"),
    ("backend/app/services/multi_affix_compare.py", "/tmp/multi_affix_compare.py"),
]


def main() -> None:
    root = __file__.replace("\\", "/").rsplit("/scripts/", 1)[0]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(NAS_HOST, NAS_PORT, NAS_USER, NAS_PASS, timeout=15)

    for rel, remote in FILES:
        local = f"{root}/{rel}"
        payload = base64.b64encode(open(local, "rb").read()).decode("ascii")
        cmd = (
            "python3 - <<'PY'\n"
            "import base64\n"
            f"open('{remote}','wb').write(base64.b64decode('{payload}'))\n"
            "print('wrote', len(open('" + remote + "','rb').read()))\n"
            "PY"
        )
        _, out, err = client.exec_command(cmd)
        code = out.channel.recv_exit_status()
        print(out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace"))
        if code != 0:
            raise SystemExit(f"upload failed for {rel}")

    for cmd in [
        "/usr/local/bin/docker cp /tmp/trade_agent.py poe2li-backend:/app/app/services/trade_agent.py",
        "/usr/local/bin/docker cp /tmp/trade_concepts.py poe2li-backend:/app/app/services/trade_concepts.py",
        "/usr/local/bin/docker cp /tmp/chat_tools.py poe2li-backend:/app/app/services/chat_tools.py",
        "/usr/local/bin/docker cp /tmp/chat_agent.py poe2li-backend:/app/app/services/chat_agent.py",
        "/usr/local/bin/docker cp /tmp/multi_affix_compare.py poe2li-backend:/app/app/services/multi_affix_compare.py",
        "/usr/local/bin/docker restart poe2li-backend",
    ]:
        print(">", cmd)
        _, out, err = client.exec_command(cmd)
        code = out.channel.recv_exit_status()
        print(out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace"), "exit", code)
        if code != 0:
            raise SystemExit("docker step failed")

    client.close()
    print("deploy ok")


if __name__ == "__main__":
    main()
