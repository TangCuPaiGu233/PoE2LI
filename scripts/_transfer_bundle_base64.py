import sys
from pathlib import Path
sys.path.insert(0, str(Path('D:/PC_AI/Project/PoE2LI')))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from scripts.remote_ssh import connect_nas, connect_tencent, run

NAS_BUNDLE = "/tmp/poe2li-tencent-bundle.bundle"
LOCAL_BUNDLE = "D:/PC_AI/Project/PoE2LI/nas_bundle/poe2li-tencent-bundle.bundle"
TENCENT_BUNDLE = "/opt/PoE2LI/poe2li-tencent-bundle.bundle"

Path("D:/PC_AI/Project/PoE2LI/nas_bundle").mkdir(exist_ok=True)

print("Reading bundle from NAS via base64...")
nas = connect_nas()
try:
    stdin, stdout, stderr = nas.exec_command(f"base64 {NAS_BUNDLE}", timeout=180)
    b64_bytes = stdout.read()
    code = stdout.channel.recv_exit_status()
    if code != 0:
        err = stderr.read().decode('utf-8', errors='replace')
        raise RuntimeError(f"NAS base64 failed: {err}")
    b64_data = b64_bytes.decode('ascii')
    print(f"NAS bundle base64 size: {len(b64_data)} chars")
finally:
    nas.close()

print("Writing bundle locally...")
with open(LOCAL_BUNDLE, 'w', encoding='ascii') as f:
    f.write(b64_data)
print(f"Saved to {LOCAL_BUNDLE}")

print("Uploading bundle to Tencent via base64...")
tencent = connect_tencent()
try:
    decode_cmd = f"cat > {TENCENT_BUNDLE} | base64 -d"
    stdin, stdout, stderr = tencent.exec_command(decode_cmd, timeout=180)
    stdin.write(b64_data)
    stdin.close()
    code = stdout.channel.recv_exit_status()
    if code != 0:
        err = stderr.read().decode('utf-8', errors='replace')
        raise RuntimeError(f"Tencent base64 decode failed: {err}")
    print(f"Uploaded bundle to {TENCENT_BUNDLE}")
finally:
    tencent.close()
