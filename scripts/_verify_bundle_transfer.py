import sys
from pathlib import Path
sys.path.insert(0, str(Path('D:/PC_AI/Project/PoE2LI')))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from scripts.remote_ssh import connect_nas, connect_tencent, run

NAS_BUNDLE = "/tmp/poe2li-tencent-bundle.bundle"
TENCENT_BUNDLE = "/opt/PoE2LI/poe2li-tencent-bundle.bundle"

print("Verifying bundle on NAS and Tencent...")
nas = connect_nas()
try:
    code, out, _ = run(nas, f"wc -c < {NAS_BUNDLE}", timeout=10, echo=False)
    nas_size = out.strip()
    print(f"NAS bundle size: {nas_size}")
finally:
    nas.close()

tencent = connect_tencent()
try:
    code, out, _ = run(tencent, f"wc -c < {TENCENT_BUNDLE}", timeout=10, echo=False)
    tencent_size = out.strip()
    print(f"Tencent bundle size: {tencent_size}")
    if nas_size == tencent_size:
        print("Sizes match.")
    else:
        print("Size mismatch!")
        code, out, _ = run(tencent, f"head -c 8 {TENCENT_BUNDLE} | xxd", timeout=10, echo=False)
        print(out.rstrip())
        raise RuntimeError("Bundle size mismatch")
finally:
    tencent.close()
