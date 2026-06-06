"""AI service for generating build playbooks.

Uses mimo-v2.5 (Anthropic-compatible API) to generate Chinese build guides.
Proxy is configured via HTTPS_PROXY/HTTP_PROXY environment variables.
"""

import os
import json
import re
from anthropic import Anthropic
from app.models.schemas import DecodeResponse

# mimo-v2.5 API (Anthropic-compatible)
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://token-plan-cn.xiaomimimo.com/anthropic")
ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "tp-c439jd6uhy2mbragl3fwwoa8w2ige8td81ggbsrs86ibsraq")

# Client uses proxy from HTTPS_PROXY/HTTP_PROXY env vars automatically
client = Anthropic(
    base_url=ANTHROPIC_BASE_URL,
    api_key=ANTHROPIC_AUTH_TOKEN,
)


def _build_prompt(build_data: DecodeResponse) -> str:
    """Build a prompt for the AI to generate a Chinese playbook."""
    build = build_data.build
    stats = build_data.playerStats
    tree = build_data.treeSpecs
    skills = build_data.skillSets
    items = build_data.items

    # Extract key stats
    life = stats.get("Life", "N/A")
    mana = stats.get("Mana", "N/A")
    dps = stats.get("TotalDPS", "N/A")
    ehp = stats.get("TotalEHP", "N/A")
    str_val = stats.get("Str", "N/A")
    dex_val = stats.get("Dex", "N/A")
    int_val = stats.get("Int", "N/A")
    fire_res = stats.get("FireResist", "N/A")
    cold_res = stats.get("ColdResist", "N/A")
    lightning_res = stats.get("LightningResist", "N/A")

    # Group skills by socket group (SkillSet > Skill > Gem)
    # PoB organizes gems into socket groups — each Skill in a SkillSet is one socket group
    companions = []
    socket_groups = []
    for ss in skills:
        # Each ss.gems is a flat list, but they come from multiple Skill elements
        # Group by slot
        current_slot = None
        current_gems = []
        for g in ss.gems:
            if not g.nameSpec or not g.enabled:
                continue
            if g.slot != current_slot:
                if current_gems:
                    socket_groups.append({"slot": current_slot, "gems": current_gems})
                current_slot = g.slot
                current_gems = []
            current_gems.append(g)
        if current_gems:
            socket_groups.append({"slot": current_slot, "gems": current_gems})

    # Also collect companions separately for highlighting
    for sg in socket_groups:
        for g in sg["gems"]:
            if "companion" in (g.nameSpec or "").lower() or "Companion" in (g.nameSpec or ""):
                companions.append(g)

    gems_str = ""
    if companions:
        gems_str += "=== Companion（伙伴）— 这是构建核心 ===\n"
        for c in companions:
            gems_str += f"- **{c.nameSpec}** Lv{c.level} Q{c.quality}\n"
        gems_str += "\n"

    gems_str += "=== Socket Groups（技能组合）===\n"
    for sg in socket_groups:
        slot = sg["slot"] or "unknown"
        gem_names = [f"{g.nameSpec}(Lv{g.level})" for g in sg["gems"]]
        gems_str += f"[{slot}] {' + '.join(gem_names)}\n"
    if not gems_str:
        gems_str = "未配置"

    # Extract items with FULL raw text, filter useless lines
    USELESS_LINES = {"Unique ID", "Item Level", "Quality", "Sockets", "Rune:", "LevelReq:"}
    item_list = []
    for i in items:
        if not i.name:
            continue
        # Get all lines of raw text, filter out noise
        raw_lines = i.raw.split("\n") if i.raw else []
        filtered = []
        for line in raw_lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Skip useless metadata lines
            if any(stripped.startswith(prefix) for prefix in USELESS_LINES):
                continue
            filtered.append(stripped)
        item_text = "\n  ".join(filtered)
        item_list.append(f"[{i.rarity}] {i.name}\n  {item_text}")
    items_str = "\n\n".join(item_list[:15]) or "无装备数据"

    # Extract tree info
    node_count = sum(len(ts.nodes) for ts in tree)

    return f"""你是一个 Path of Exile 2 构建分析专家。请仔细分析以下构建数据，生成一份中文攻略。

特别注意：
- Companion（伙伴）是 PoE2 的独特机制，它们是独立战斗的 AI 伙伴，有自己的技能和行为
- 如果有 Companion，必须详细分析每个 Companion 的作用和它们的辅助宝石搭配
- 装备数据包含完整词缀，仔细阅读词缀来判断装备的核心价值
- 特别关注带有 "Minion"（召唤物）"Companion" 关键词的词缀
- 分析这个构建的核心玩法思路，不要泛泛而谈
- 如果 DPS 为 0 但有 Companion/Minion，说明伤害来自伙伴而非角色本身

## 构建信息
- 职业: {build.className} / {build.ascendClassName}
- 等级: {build.level}
- 天赋节点数: {node_count}

## 关键属性
- 生命: {life}
- 魔力: {mana}
- DPS: {dps}
- EHP: {ehp}
- 力量/敏捷/智慧: {str_val}/{dex_val}/{int_val}
- 抗性: 火{fire_res} / 冰{cold_res} / 电{lightning_res}

## 技能宝石（按 Socket Group 分组）
{gems_str}

## 装备（完整词缀）
{items_str}

## 输出要求
1. 用中文回答
2. 基于实际数据分析，不要编造不存在的装备或技能
3. 重点分析这个构建的核心输出手段和独特玩法
4. 如果有 Companion/Minion/Totem，详细说明它们的作用
5. 给出实用的建议

请严格按以下 JSON 格式输出，每个字段的值必须是纯字符串：
{{
  "core_idea": "核心思路：分析这个构建的核心输出手段和玩法特色",
  "core_items": "核心装备：列出关键装备及其作用",
  "budget_alternatives": "预算替代：低成本替代方案",
  "talent_highlights": "天赋亮点：关键天赋节点选择",
  "strength_review": "强度评估：优劣势和适用场景"
}}"""


def _fix_keys(result: dict) -> dict:
    """Fix common AI typos in JSON keys."""
    KEY_MAP = {
        "core_idea": "core_idea",
        "core_ista": "core_idea",
        "core_id": "core_idea",
        "core_ide": "core_idea",
        "core_items": "core_items",
        "core_item": "core_items",
        "budget_alternatives": "budget_alternatives",
        "budget_alternative": "budget_alternatives",
        "budget_alternatives": "budget_alternatives",
        "talent_highlights": "talent_highlights",
        "talent_highlight": "talent_highlights",
        "talent_points": "talent_highlights",
        "talent_point": "talent_highlights",
        "strength_review": "strength_review",
        "strength_reviews": "strength_review",
    }
    fixed = {}
    for k, v in result.items():
        canonical = KEY_MAP.get(k, k)
        # If already exists, merge (prefer longer content)
        if canonical in fixed:
            if len(str(v)) > len(str(fixed[canonical])):
                fixed[canonical] = v
        else:
            fixed[canonical] = v
    return fixed


def _parse_ai_response(content: str) -> dict:
    """Parse AI response, handling various formats robustly."""
    # Try direct JSON parse first
    try:
        return _fix_keys(json.loads(content))
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code blocks
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if json_match:
        try:
            return _fix_keys(json.loads(json_match.group(1)))
        except json.JSONDecodeError:
            pass

    # Try finding any JSON object in the content
    brace_start = content.find('{')
    brace_end = content.rfind('}')
    if brace_start >= 0 and brace_end > brace_start:
        json_str = content[brace_start:brace_end + 1]
        try:
            return _fix_keys(json.loads(json_str))
        except json.JSONDecodeError:
            # Try fixing common JSON issues
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            try:
                return _fix_keys(json.loads(json_str))
            except json.JSONDecodeError:
                pass

    # If all else fails, try to extract key-value pairs manually
    # Also handle fuzzy key names (typos like core_ista -> core_idea)
    result = {}
    fuzzy_patterns = {
        "core_idea": [r"core_idea", r"core_ista", r"core_id", r"core_ide[a-z]?"],
        "core_items": [r"core_items?", r"core_item"],
        "budget_alternatives": [r"budget_alternatives?", r"budget_alternative"],
        "talent_highlights": [r"talent_highlights?", r"talent_highlight", r"talent_points?"],
        "strength_review": [r"strength_reviews?", r"strength_review"],
    }
    for canonical, patterns in fuzzy_patterns.items():
        for pat in patterns:
            # Look for "key": "value" pattern
            pattern = rf'"{pat}"\s*:\s*"((?:[^"\\]|\\.)*)"'
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                result[canonical] = match.group(1)
                break
            # Look for 'key': 'value' pattern
            pattern = rf"'{pat}'\s*:\s*'((?:[^'\\]|\\.)*)'"
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                result[canonical] = match.group(1)
                break

    if result:
        return _fix_keys(result)

    raise ValueError(f"Could not parse AI response as JSON: {content[:200]}...")


def generate_homework(build_data: DecodeResponse) -> dict:
    """Generate a Chinese playbook from BuildData using mimo-v2.5.

    Returns a dict with five sections:
    - core_idea: Build philosophy and playstyle
    - core_items: Essential equipment
    - budget_alternatives: Cheaper substitutes
    - talent_highlights: Notable passive tree choices
    - strength_review: Build strengths and weaknesses
    """
    prompt = _build_prompt(build_data)

    try:
        response = client.messages.create(
            model="mimo-v2.5",
            max_tokens=4000,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        # Parse response — find text content (skip thinking blocks)
        content = ""
        for block in response.content:
            if block.type == "text":
                content = block.text
                break
        if not content:
            raise ValueError("AI response contained no text content")

        # Parse JSON from response
        result = _parse_ai_response(content)

        # Validate and flatten required fields
        for key in ["core_idea", "core_items", "budget_alternatives", "talent_highlights", "strength_review"]:
            if key not in result:
                result[key] = f"AI 未生成 {key} 内容"
            elif isinstance(result[key], dict):
                desc = result[key].get("description", "")
                if not desc:
                    desc = str(result[key])
                result[key] = desc
            elif not isinstance(result[key], str):
                result[key] = str(result[key])

        return result

    except Exception as e:
        # Fallback: generate basic analysis from data
        build = build_data.build
        stats = build_data.playerStats
        items = build_data.items
        skills = build_data.skillSets

        # Try to identify key items
        unique_items = [i.name for i in items if i.rarity == "UNIQUE" and i.name]
        key_items_str = "、".join(unique_items[:5]) if unique_items else "未知"

        # Try to identify main skill
        main_gems = []
        for ss in skills:
            for g in ss.gems:
                if g.enabled and g.nameSpec and g.level >= 15:
                    main_gems.append(g.nameSpec)
        main_skill_str = "、".join(main_gems[:3]) if main_gems else "未知"

        return {
            "core_idea": f"{build.className} / {build.ascendClassName} 构建，等级 {build.level}。主要技能: {main_skill_str}。DPS: {stats.get('TotalDPS', 'N/A')}。AI 分析失败: {e}",
            "core_items": f"核心装备: {key_items_str}",
            "budget_alternatives": "暂无数据（AI 生成失败）",
            "talent_highlights": f"天赋树共 {sum(len(ts.nodes) for ts in build_data.treeSpecs)} 个节点",
            "strength_review": f"生命: {stats.get('Life', 'N/A')}, DPS: {stats.get('TotalDPS', 'N/A')}",
        }
