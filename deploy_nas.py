import paramiko, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
NAS_HOST = "192.168.110.26"
NAS_PORT = 2212
NAS_USER = "skc"
NAS_PASS = "SKChaidao@123"
NAS_GIT_REF = os.getenv("NAS_GIT_REF", "main")
NAS_PROJECT_DIR = "/volume1/docker/PoE2LI"

CHAT_IMAGE_LIB = "frontend/src/lib/chatImage.ts"
CHAT_PAGE = "frontend/src/app/chat/page.tsx"
def verify_frontend_chat_features_remote(client: paramiko.SSHClient) -> None:
    """Run the same guard on the NAS checkout before docker build."""
    checks = " && ".join([
        f"test -f {NAS_PROJECT_DIR}/{CHAT_IMAGE_LIB}",
        f"test -f {NAS_PROJECT_DIR}/{CHAT_PAGE}",
        (
            f"grep -Eq 'chatImage|粘贴截图|Ctrl\\+V' "
            f"{NAS_PROJECT_DIR}/{CHAT_PAGE}"
        ),
    ])
    cmd = f"cd {NAS_PROJECT_DIR} && {checks}"
    stdin, stdout, stderr = client.exec_command(cmd)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        err = stderr.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "Deploy blocked: NAS checkout is missing chat image paste UI. "
            f"Merge chat image changes into origin/{NAS_GIT_REF} first. "
            + (f"Remote check: {err}" if err else "")
        )


client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print(f"Connecting to {NAS_HOST}:{NAS_PORT}...")
    client.connect(NAS_HOST, NAS_PORT, NAS_USER, NAS_PASS, timeout=10)
    print("Connected successfully!")

    git_sync = (
        f"cd {NAS_PROJECT_DIR} && if [ -d .git ]; then "
        f"echo 'Fetching and resetting to origin/{NAS_GIT_REF}...' && "
        f"git fetch origin && git reset --hard origin/{NAS_GIT_REF}; "
        f"else echo 'Cloning...' && "
        f"git clone https://github.com/TangCuPaiGu233/PoE2LI.git .; fi"
    )

    commands = [
        f"mkdir -p {NAS_PROJECT_DIR}",
        git_sync,
        f"cd {NAS_PROJECT_DIR} && /usr/local/bin/docker compose up -d --build --force-recreate",
    ]

    for cmd in commands:
        print(f"\nExecuting: {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd)
        raw_output = stdout.read()
        try:
            output = raw_output.decode('utf-8')
        except UnicodeDecodeError:
            output = raw_output.decode('latin-1')
        print(output)
        raw_err = stderr.read()
        try:
            err = raw_err.decode('utf-8')
        except UnicodeDecodeError:
            err = raw_err.decode('latin-1')
        if err:
            print(f"STDERR:\n{err}")
        exit_status = stdout.channel.recv_exit_status()
        print(f"Exit status: {exit_status}")
        if exit_status != 0:
            print("Command failed! Stopping deployment.")
            sys.exit(1)

        if cmd == git_sync:
            print("Verifying chat image UI is present before frontend rebuild...")
            verify_frontend_chat_features_remote(client)

    print("\nDeployment completed successfully!")

except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
finally:
    client.close()
