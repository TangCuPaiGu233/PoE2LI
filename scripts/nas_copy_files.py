"""Copy files to NAS via SSH base64 pipe."""
import paramiko, base64, sys, os

NAS_PROJECT = "/volume1/docker/PoE2LI"

FILES_TO_COPY = [
    "docker-compose.yml",
    "backend/requirements.txt",
]

def b64encode_file(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.110.26", 2212, "skc", "SKChaidao@123", timeout=10)

for rel_path in FILES_TO_COPY:
    local_path = rel_path
    nas_path = f"{NAS_PROJECT}/{rel_path}"
    b64 = b64encode_file(local_path)
    print(f"Copying {rel_path} ({len(b64)} base64 chars)...", end=" ")

    cmd = f'echo "{b64}" | base64 -d > {nas_path}'
    stdin, stdout, stderr = client.exec_command(cmd)
    err = stderr.read().decode(errors="replace")
    if err:
        print(f"ERR: {err[:100]}")
    else:
        # Verify
        _, o, _ = client.exec_command(f"wc -c < {nas_path}")
        size = o.read().decode().strip()
        print(f"OK ({size} bytes)")

client.close()
print("DONE")
