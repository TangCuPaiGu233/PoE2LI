"""Query NAS database and container status."""
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.110.26", 2212, "skc", "SKChaidao@123", timeout=10)

DOCKER = "/usr/local/bin/docker"

def run_sql(sql):
    clean = " ".join(sql.split())
    cmd = f'{DOCKER} exec poe2li-postgres psql -U poe2li -d poe2li -c "{clean}"'
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    if err and "WARNING" not in err and "ERROR" in err:
        print("STDERR:", err[:300])
    return out

print("=== CONTAINERS ===")
s, o, e = client.exec_command(f"{DOCKER} ps")
print(o.read().decode(errors="replace"))

print("=== DATABASES ===")
print(run_sql(r"\l"))

print("=== TABLE SIZES ===")
print(run_sql("SELECT schemaname, relname, n_live_tup as rows, pg_size_pretty(pg_total_relation_size(relid)) as total_size FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 20;"))

print("=== KEY COUNTS ===")
for tbl in ["builds", "knowledge_chunks", "kb_entities", "kb_edges", "mod_translations"]:
    print(run_sql(f"SELECT count(*) as {tbl} FROM {tbl};"))

print("=== CHUNK LEAGUE/VERSION DISTRIBUTION ===")
print(run_sql("SELECT league, game_version, count(*) FROM knowledge_chunks GROUP BY league, game_version ORDER BY count(*) DESC LIMIT 10;"))

print("=== BUILDS ===")
print(run_sql("SELECT id, class, ascendancy, main_skill, level, status, source, created_at FROM builds ORDER BY id DESC LIMIT 5;"))

print("=== BUILD LEAGUE/VERSION ===")
print(run_sql("SELECT league, game_version, count(*) FROM builds GROUP BY league, game_version;"))

print("=== DB SIZE ===")
print(run_sql("SELECT pg_size_pretty(pg_database_size('poe2li')) as db_size;"))

print("=== VECTOR EXTENSION ===")
print(run_sql("SELECT extname, extversion FROM pg_extension;"))

print("=== LANG FUSE DB CHECK ===")
s, o, e = client.exec_command(f'{DOCKER} exec poe2li-postgres psql -U poe2li -c "SELECT 1 FROM pg_database WHERE datname=\'poe2li_langfuse\';"')
print(o.read().decode(errors="replace"))

print("=== DISK ===")
s, o, e = client.exec_command("df -h /volume1/docker/")
print(o.read().decode(errors="replace"))

print("=== MEMORY ===")
s, o, e = client.exec_command("free -h")
print(o.read().decode(errors="replace"))

client.close()
print("\n=== DONE ===")
