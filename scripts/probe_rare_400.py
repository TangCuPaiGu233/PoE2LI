"""Probe CN trade API 400 for PoB rare ring queries."""
import base64
import io
import sys

import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST, PORT, USER, PASS = "192.168.110.26", 2212, "skc", "SKChaidao@123"
DOCKER = "/usr/local/bin/docker"

PY = """
import json
import os
import cloudscraper
from urllib.parse import quote

from app.services.pob_rare_trade import (
    build_pob_rare_stat_groups,
    item_type_for_pob_item,
    parse_pob_item_mods,
    resolve_pob_mods_to_stats,
)
from app.services.trade_realm import resolve_league, search_api_url
from app.services.trade_service import build_trade_query

SAMPLE_RAW = (
    "Rarity: RARE\\n"
    "Probe Ring\\n"
    "Ruby Ring\\n"
    "--------\\n"
    "Item Level: 82\\n"
    "+80 to maximum Life\\n"
    "45% increased Fire Damage\\n"
    "+25 to maximum Mana\\n"
)

slot = "Ring 1"
en_base = "Ruby Ring"
cn_base = "\\u7ea2\\u7389\\u6212\\u6307"

mods = parse_pob_item_mods(SAMPLE_RAW)
resolved, missed = resolve_pob_mods_to_stats(mods)
stat_groups = build_pob_rare_stat_groups(resolved)
item_type = item_type_for_pob_item(slot, en_base)

print("=== parse ===")
print("mods", len(mods), [m.line for m in mods])
print("resolved", json.dumps(resolved, ensure_ascii=False))
print("missed", missed)
print("stat_groups", json.dumps(stat_groups, ensure_ascii=False))
print("item_type", item_type)

base_intent = {
    "rarity": "rare",
    "stat_groups": stat_groups,
    "summary": "rare probe (" + en_base + ")",
}
if item_type:
    base_intent["item_type"] = item_type

variants = [
    ("en_base", {**base_intent, "base_type": en_base}),
    ("cn_base", {**base_intent, "base_type": cn_base}),
    ("no_base", dict(base_intent)),
]

LEAGUE = resolve_league("cn", None)
url = search_api_url("cn", LEAGUE)
ORIGIN = "https://poe.game.qq.com"
sess = os.getenv("TRADE_CN_POESESSID", "")

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)
scraper.headers.update({
    "Accept": "application/json",
    "Origin": ORIGIN,
    "Referer": ORIGIN + "/trade2/search/poe2/" + quote(LEAGUE),
})
if sess:
    scraper.cookies.set("POESESSID", sess, domain="poe.game.qq.com")
else:
    print("WARN: TRADE_CN_POESESSID not set")

for label, intent in variants:
    body = build_trade_query(intent, market="cn")
    print("\\n=== POST", label, "===")
    print("intent base_type", intent.get("base_type"))
    print("body", json.dumps(body, ensure_ascii=False))
    try:
        r = scraper.post(url, json=body, timeout=30)
        print("status", r.status_code)
        print("response", r.text)
    except Exception as e:
        print("request_error", e)
"""


def main() -> None:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, PORT, USER, PASS, timeout=15)
    b64 = base64.b64encode(PY.encode("utf-8")).decode("ascii")
    cmd = (
        f"{DOCKER} exec poe2li-backend python -c "
        f"\"import base64; exec(base64.b64decode('{b64}').decode())\""
    )
    _, stdout, stderr = client.exec_command(cmd, timeout=180)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    print(out)
    if err.strip():
        print("STDERR:", err)
    code = stdout.channel.recv_exit_status()
    print(f"[exit {code}]")
    client.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
