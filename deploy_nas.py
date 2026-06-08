"""Deploy PoE2LI to NAS via SSH — git sync + docker rebuild.

.env is NEVER touched during deploy — it's user-managed persistent state.
Only created once from .env.example if it doesn't exist.
"""

import paramiko
import sys
import io
import os

# Force UTF-8 output to avoid GBK encoding errors with Unicode characters
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

NAS_HOST = "192.168.110.26"
NAS_PORT = 2212
NAS_USER = "skc"
NAS_PASS = "SKChaidao@123"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print(f"Connecting to {NAS_HOST}:{NAS_PORT}...")
    client.connect(NAS_HOST, NAS_PORT, NAS_USER, NAS_PASS, timeout=10)
    print("Connected successfully!")

    commands = [
        "mkdir -p /volume1/docker/PoE2LI",
        "cd /volume1/docker/PoE2LI && if [ -d .git ]; then echo 'Fetching and resetting...' && git fetch origin && git reset --hard origin/main; else echo 'Cloning...' && git clone https://github.com/TangCuPaiGu233/PoE2LI.git .; fi",
        # NEVER overwrite .env — only create from example if it doesn't exist
        """cd /volume1/docker/PoE2LI && if [ ! -f .env ]; then
echo 'Creating .env from .env.example (edit with your API keys!)'
cp .env.example .env
else
echo '.env exists — preserved (not modified by deploy)'
fi""",
        "cd /volume1/docker/PoE2LI && /usr/local/bin/docker compose up -d --build --force-recreate",
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

    print("\nDeployment completed successfully!")

except Exception as e:
    print(f"Error: {e}")
finally:
    client.close()
