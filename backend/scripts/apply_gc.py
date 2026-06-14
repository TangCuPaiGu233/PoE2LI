# -*- coding: utf-8 -*-
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rw(rel, fn):
    p = ROOT / rel
    t = p.read_text(encoding="utf-8")
    n = fn(t)
    if n != t:
        p.write_text(n, encoding="utf-8")
        return True
    return False


def chat(t):
    imp = "from app.core.game_context import POE2_SITE_RULE, is_ninja_cost_guide_query, NINJA_COST_GUIDE_MARKDOWN"
    if imp not in t:
        a = "from app.services.follow_up_suggestions import generate_follow_up_questions"
        t = t.replace(a, a + "\n\n" + imp, 1)
    if " + POE2_SITE_RULE + " not in t:
        o = 'AGENT_SYSTEM = """'
        ix = t.index(o)
        ix2 = t.index("\n\n## ", ix)
        fl = t[ix + len(o) : ix2]
        t = t[:ix] + o + fl + '""" + POE2_SITE_RULE + """' + t[ix2:]
    wg = next((ln for ln in t.splitlines() if ln.startswith("11. **WeGame")), None)
    ninja = (
        "11. **poe.ninja BD \u9020\u4ef7\uff08\u65e0\u94fe\u63a5\uff09**\uff1a\u7528\u6237\u63d0\u5230"
        "\u5fcd\u8005\u7f51/poe.ninja \u5e76\u8be2\u95ee BD \u9020\u4ef7\uff0c\u4f46\u6d88\u606f\u91cc\u6ca1\u6709"
        " poe.ninja \u89d2\u8272\u94fe\u63a5\u3001PoB \u7801\u7b49\u53ef\u89e3\u6790\u6784\u5efa\u8f93\u5165\u65f6\uff0c"
        "\u76f4\u63a5\u8bf4\u660e\u5982\u4f55\u590d\u5236\u5e76\u7c98\u8d34\u94fe\u63a5\uff0c\u4e0d\u8981\u8c03\u7528"
        " decode_pob \u6216 BD \u9020\u4ef7\u6d41\u6c34\u7ebf\u3002"
    )
    if wg and ninja not in t:
        t = t.replace(wg, ninja + "\n" + wg.replace("11. ", "12. ", 1), 1)
    key = "    if is_build_cost_query(user_msg):"
    ins = (
        "    if is_ninja_cost_guide_query(user_msg):\n"
        '        yield {"type": "answer", "content": NINJA_COST_GUIDE_MARKDOWN}\n'
        "        async for ev in _yield_done_with_follow_ups(user_msg, NINJA_COST_GUIDE_MARKDOWN):\n"
        "            yield ev\n"
        "        return\n\n"
        + key
    )
    if "is_ninja_cost_guide_query(user_msg)" not in t:
        t = t.replace(key, ins, 1)
    return t


def ai(t):
    imp = "from app.core.game_context import attach_poe2_rule"
    if imp not in t:
        t = t.replace(
            "from app.models.build import ModTranslation",
            "from app.models.build import ModTranslation\n" + imp,
            1,
        )
    if "HOMEWORK_SYSTEM_PROMPT = attach_poe2_rule(" in t:
        return t
    t = t.replace("HOMEWORK_SYSTEM_PROMPT = ", "HOMEWORK_SYSTEM_PROMPT = attach_poe2_rule(", 1)
    t = t.replace('\n}"""\n\nCHAT_SYSTEM_PROMPT = ', '\n}""")\n\nCHAT_SYSTEM_PROMPT = attach_poe2_rule(', 1)
    if "CHAT_SYSTEM_PROMPT = attach_poe2_rule(" in t and not re.search(
        r"CHAT_SYSTEM_PROMPT = attach_poe2_rule\(\"\"\"[\s\S]*?\"\"\"\)", t
    ):
        t = re.sub(
            r"(CHAT_SYSTEM_PROMPT = attach_poe2_rule\(\"\"\"[\s\S]*?\"\"\")(\n)",
            r"\1)\2",
            t,
            count=1,
        )
    return t


def skill_import(t):
    imp = "from app.core.game_context import attach_poe2_rule"
    if imp in t:
        return t
    lines = t.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("from app.skills.base"):
            lines.insert(i, imp)
            return "\n".join(lines) + "\n"
    return t


def skill_join(t):
    t = skill_import(t)
    o = '        return "".join(parts)'
    n = '        return attach_poe2_rule("".join(parts))'
    return t.replace(o, n, 1) if n not in t else t


def skill_paren(t):
    t = skill_import(t)
    if "return attach_poe2_rule(" in t:
        return t
    return t.replace("        return (", "        return attach_poe2_rule(", 1)


def know(t):
    imp = "from app.core.game_context import POE2_SITE_RULE"
    if imp not in t:
        t = t.replace(
            "from app.services.retrieval_pipeline import (",
            imp + "\n\nfrom app.services.retrieval_pipeline import (",
            1,
        )
    if "{POE2_SITE_RULE}" in t:
        return t
    return t.replace("    sys_prompt = f\"\"\"", "    sys_prompt = f\"\"\"{POE2_SITE_RULE}\n\n", 1)


def rec(t):
    imp = "from app.core.game_context import attach_poe2_rule"
    if imp not in t:
        t = t.replace(
            "from app.core.redis_client import get_redis",
            "from app.core.redis_client import get_redis\n" + imp,
            1,
        )
    for line in t.splitlines():
        if '"role": "system"' in line and "{context}" in line and "attach_poe2_rule" not in line:
            new = line.replace('"content": f"', '"content": attach_poe2_rule(f"')
            if new.endswith('"},'):
                new = new[:-3] + '")},'
            t = t.replace(line, new, 1)
            break
    return t


def fu(t):
    imp = "from app.core.game_context import POE2_SITE_RULE"
    if imp not in t:
        t = t.replace("logger = logging.getLogger(__name__)", "logger = logging.getLogger(__name__)\n\n" + imp, 1)
    if "FOLLOW_UP_SYSTEM = POE2_SITE_RULE" in t:
        return t
    return t.replace("FOLLOW_UP_SYSTEM = \"\"\"", "FOLLOW_UP_SYSTEM = POE2_SITE_RULE + \"\\n\\n\" + \"\"\"", 1)


def write_tests():
    p = ROOT / "tests/test_game_context.py"
    body = (
        '"""Tests for app.core.game_context helpers."""\n\n'
        "import pytest\n\n"
        "from app.core.game_context import is_ninja_cost_guide_query\n\n\n"
        "@pytest.mark.parametrize(\n"
        '    "msg,expected",\n'
        "    [\n"
        '        ("\u5e2e\u6211\u4f30\u7b97\u5fcd\u8005\u7f51BD\u9020\u4ef7", True),\n'
        '        ("poe.ninja \u8fd9\u5957 bd \u9020\u4ef7\u591a\u5c11", True),\n'
        '        ("\u5fcd\u8005\u7f51\u7b97\u4e00\u4e0b\u8fd9\u5957\u6784\u5efa\u9020\u4ef7", True),\n'
        '        ("https://poe.ninja/poe2/builds/x/character/a/b \u7b97\u9020\u4ef7", False),\n'
        '        ("eNabcd \u7b97\u4e00\u4e0b\u9020\u4ef7", False),\n'
        '        ("\u5fcd\u8005\u7f51\u662f\u4ec0\u4e48", False),\n'
        '        ("", False),\n'
        "    ],\n"
        ")\n"
        "def test_is_ninja_cost_guide_query(msg: str, expected: bool) -> None:\n"
        "    assert is_ninja_cost_guide_query(msg) is expected\n"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    if old.strip() != body.strip():
        p.write_text(body, encoding="utf-8")
        return True
    return False


def main():
    changed = []
    for rel, fn in [
        ("app/services/chat_agent.py", chat),
        ("app/services/ai_service.py", ai),
        ("app/skills/build_design.py", skill_join),
        ("app/skills/encyclopedia.py", skill_join),
        ("app/skills/recommend.py", skill_paren),
        ("app/skills/trade_search.py", skill_paren),
        ("app/api/knowledge.py", know),
        ("app/api/api_recommend.py", rec),
        ("app/services/follow_up_suggestions.py", fu),
    ]:
        if rw(rel, fn):
            changed.append(rel)
    if write_tests():
        changed.append("tests/test_game_context.py")
    print("CHANGED:", ",".join(changed) if changed else "(none)")


if __name__ == "__main__":
    main()