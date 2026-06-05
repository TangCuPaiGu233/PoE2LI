"""Deploy PoE2LI to NAS via SSH."""

import paramiko
import time

NAS_HOST = "192.168.110.26"
NAS_PORT = 2212
NAS_USER = "skc"
NAS_PASS = "SKChaidao@123"
PROJECT_DIR = "/volume1/docker/poe2li"

def run_cmd(ssh, cmd, timeout=60):
    """Run a command and return output."""
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if out:
        print(out)
    if err and "WARNING" not in err:
        print(f"STDERR: {err}")
    return out, err

def main():
    print("Connecting to NAS...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(NAS_HOST, port=NAS_PORT, username=NAS_USER, password=NAS_PASS)
    print("Connected!")

    try:
        # 1. Create project directory
        run_cmd(ssh, f"mkdir -p {PROJECT_DIR}")

        # 2. Configure git proxy and clone/pull
        run_cmd(ssh, "git config --global http.proxy http://192.168.110.26:7890")
        run_cmd(ssh, "git config --global https.proxy http://192.168.110.26:7890")

        out, _ = run_cmd(ssh, f"test -d {PROJECT_DIR}/.git && echo 'exists' || echo 'new'")
        if "exists" in out:
            print("Repo exists, pulling...")
            run_cmd(ssh, f"cd {PROJECT_DIR} && git pull", timeout=120)
        else:
            print("Cloning repo...")
            run_cmd(ssh, f"cd {PROJECT_DIR} && git clone https://github.com/TangCuPaiGu233/PoE2LI.git .", timeout=120)

        # 3. Create .env file
        env_content = (
            "ANTHROPIC_AUTH_TOKEN=tp-c439jd6uhy2mbragl3fwwoa8w2ige8td81ggbsrs86ibsraq\\n"
            "HTTPS_PROXY=http://192.168.110.26:7890\\n"
            "HTTP_PROXY=http://192.168.110.26:7890"
        )
        run_cmd(ssh, f'echo -e "{env_content}" > {PROJECT_DIR}/.env')
        run_cmd(ssh, f"cat {PROJECT_DIR}/.env")

        # 4. Build and start
        print("\nBuilding and starting containers (this may take a few minutes)...")
        run_cmd(ssh, f"cd {PROJECT_DIR} && export PATH='/usr/local/bin:$PATH' && /usr/local/bin/docker compose up -d --build", timeout=300)

        # 5. Check status
        time.sleep(5)
        run_cmd(ssh, f"cd {PROJECT_DIR} && /usr/local/bin/docker compose ps")
        run_cmd(ssh, f"cd {PROJECT_DIR} && /usr/local/bin/docker compose logs --tail=20")

        print("\nDeployment complete!")
        print(f"Frontend: http://{NAS_HOST}:3000")
        print(f"Backend: http://{NAS_HOST}:8000")
        print(f"Swagger: http://{NAS_HOST}:8000/docs")

    finally:
        ssh.close()

if __name__ == "__main__":
    main()
