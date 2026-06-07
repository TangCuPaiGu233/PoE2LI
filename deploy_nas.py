import paramiko
import sys

hostname = "192.168.110.26"
port = 2212
username = "skc"
password = "SKChaidao@123"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print(f"Connecting to {hostname}:{port}...")
    client.connect(hostname, port, username, password, timeout=10)
    print("Connected successfully!")
    
    commands = [
        "mkdir -p /volume1/docker/PoE2LI",
        "cd /volume1/docker/PoE2LI && if [ -d .git ]; then echo 'Pulling...' && git pull; else echo 'Cloning...' && git clone https://github.com/TangCuPaiGu233/PoE2LI.git .; fi",
        "cd /volume1/docker/PoE2LI && if [ ! -f .env ] && [ -f .env.example ]; then cp .env.example .env; echo 'Created .env from .env.example'; fi",
        "cd /volume1/docker/PoE2LI && /usr/local/bin/docker compose up -d --build"
    ]
    
    for cmd in commands:
        print(f"\nExecuting: {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd)
        
        while True:
            line = stdout.readline()
            if not line:
                break
            print(line, end="")
            
        err = stderr.read().decode()
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