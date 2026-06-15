"""Deploy chat image copy/download UI to NAS frontend."""
import base64
import pathlib
import sys

import paramiko

sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)

HOST, PORT, USER, PASS = "192.168.110.26", 2212, "skc", "SKChaidao@123"
ROOT = pathlib.Path(__file__).resolve().parents[1]
NAS_ROOT = "/volume1/docker/PoE2LI"

FILES = [
    "frontend/src/lib/chatImage.ts",
    "frontend/src/components/chat/ChatMessageImage.tsx",
    "frontend/src/components/chat/ChatMarkdown.tsx",
    "frontend/src/app/chat/page.tsx",
    "frontend/src/app/globals.css",
]


def main() -> None:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, PORT, USER, PASS, timeout=15)

    for rel in FILES:
        local = ROOT / rel
        remote = f"{NAS_ROOT}/{rel.replace(chr(92), '/')}"
        payload = base64.b64encode(local.read_bytes()).decode("ascii")
        cmd = (
            "python3 - <<'PY'\n"
            "import base64, pathlib\n"
            f"p = pathlib.Path('{remote}')\n"
            "p.parent.mkdir(parents=True, exist_ok=True)\n"
            f"p.write_bytes(base64.b64decode('{payload}'))\n"
            "print('wrote', p, 'bytes', p.stat().st_size)\n"
            "PY"
        )
        print(">", rel)
        _, out, err = client.exec_command(cmd, timeout=120)
        code = out.channel.recv_exit_status()
        print(out.read().decode("utf-8", "replace"))
        e = err.read().decode("utf-8", "replace")
        if e:
            print("stderr:", e)
        if code != 0:
            client.close()
            raise SystemExit(f"upload failed: {rel}")

    build_cmd = (
        f"cd {NAS_ROOT} && /usr/local/bin/docker compose build --no-cache frontend "
        "&& /usr/local/bin/docker compose up -d --force-recreate frontend"
    )
    print(">", build_cmd)
    _, out, err = client.exec_command(build_cmd, timeout=900)
    code = out.channel.recv_exit_status()
    text = out.read().decode("utf-8", "replace")
    print(text[-4000:] if len(text) > 4000 else text)
    e = err.read().decode("utf-8", "replace")
    if e:
        print("stderr:", e[-2000:])
    client.close()
    if code != 0:
        raise SystemExit(f"frontend build failed exit={code}")
    print("NAS frontend deploy ok")


if __name__ == "__main__":
    main()
