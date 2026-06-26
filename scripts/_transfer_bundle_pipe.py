import sys
from pathlib import Path
sys.path.insert(0, str(Path('D:/PC_AI/Project/PoE2LI')))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from scripts.remote_ssh import connect_nas, connect_tencent, run

NAS_BUNDLE = "/tmp/poe2li-tencent-bundle.bundle"
TENCENT_BUNDLE = "/opt/PoE2LI/poe2li-tencent-bundle.bundle"

print("Opening NAS and Tencent SSH sessions...")
nas = connect_nas()
tencent = connect_tencent()
try:
    print("Streaming bundle from NAS to Tencent via base64...")
    nas_cmd = f"base64 {NAS_BUNDLE}"
    tencent_cmd = f"base64 -d > {TENCENT_BUNDLE}"

    stdin_nas, stdout_nas, stderr_nas = nas.exec_command(nas_cmd, timeout=180)
    stdin_tencent, stdout_tencent, stderr_tencent = tencent.exec_command(tencent_cmd, timeout=180)

    chunk_size = 1024 * 1024
    while True:
        chunk = stdout_nas.read(chunk_size)
        if not chunk:
            break
        stdin_tencent.write(chunk)
    stdin_tencent.close()

    code_nas = stdout_nas.channel.recv_exit_status()
    code_tencent = stdout_tencent.channel.recv_exit_status()

    print(f"NAS exit: {code_nas}, Tencent exit: {code_tencent}")
    if code_nas != 0:
        err = stderr_nas.read().decode('utf-8', errors='replace')
        raise RuntimeError(f"NAS command failed: {err}")
    if code_tencent != 0:
        err = stderr_tencent.read().decode('utf-8', errors='replace')
        raise RuntimeError(f"Tencent command failed: {err}")

    print(f"Bundle transferred to {TENCENT_BUNDLE}")
finally:
    nas.close()
    tencent.close()
