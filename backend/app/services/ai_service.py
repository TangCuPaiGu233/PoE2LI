"""AI service for generating build playbooks.

Uses mimo-v2.5 (Anthropic-compatible API) to generate Chinese build guides.
Proxy is configured via HTTPS_PROXY/HTTP_PROXY environment variables.
"""

import os
import json
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

# Structured output schema for homework
HOMEWORK_SCHEMA = {
    "type": "object",
    "properties": {
        "core_idea": {
            "type": "string",
            "description": "核心思路：这个构建的核心玩法和设计理念（2-3句话）"
        },
        "core_items": {
            "type": "string",
            "description": "核心装备：必须具备的关键装备及其作用"
        },
        "budget_alternatives": {
            "type": "string",
            "description": "预算替代：低成本替代方案，适合新手过渡"
        },
        "talent_highlights": {
            "type": "string",
            "description": "天赋亮点：天赋树中的关键选择和原因"
        },
        "strength_review": {
            "type": "string",
            "description": "强度评估：构建的优劣势、适用场景和总体评分"
        }
    },
    "required": ["core_idea", "core_items", "budget_alternatives", "talent_highlights", "strength_review"]
}


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

    # Extract gems
    gem_list = []
    for ss in skills:
        for g in ss.gems:
            if g.enabled and g.nameSpec:
                gem_list.append(f"{g.nameSpec} (Lv{g.level}, Q{g.quality})")
    gems_str = "\n".join(f"- {g}" for g in gem_list[:10]) or "未配置"

    # Extract items
    item_list = []
    for i in items:
        if i.name:
            item_list.append(f"[{i.rarity}] {i.name}")
    items_str = "\n".join(f"- {i}" for i in item_list[:10]) or "无装备数据"

    # Extract tree info
    node_count = sum(len(ts.nodes) for ts in tree)

    return f"""你是一个 Path of Exile 2 构建分析专家。请根据以下构建数据，生成一份中文攻略。

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

## 技能宝石
{gems_str}

## 装备
{items_str}

## 要求
1. 用中文回答
2. 基于实际数据分析，不要编造
3. 如果数据不完整，指出缺失部分
4. 给出实用的建议

请严格按以下 JSON 格式输出，每个字段的值必须是纯字符串，不要嵌套对象：
{{
  "core_idea": "这里写核心思路的纯文本",
  "core_items": "这里写核心装备的纯文本",
  "budget_alternatives": "这里写预算替代的纯文本",
  "talent_highlights": "这里写天赋亮点的纯文本",
  "strength_review": "这里写强度评估的纯文本"
}}"""


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
            max_tokens=2000,
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

        # Try to extract JSON from response
        # Handle cases where AI wraps JSON in markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        # Find JSON object in content
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            content = content[start:end]

        result = json.loads(content)

        # Validate and flatten required fields
        for key in ["core_idea", "core_items", "budget_alternatives", "talent_highlights", "strength_review"]:
            if key not in result:
                result[key] = f"AI 未生成 {key} 内容"
            elif isinstance(result[key], dict):
                # Flatten nested objects to string
                desc = result[key].get("description", "")
                if not desc:
                    desc = str(result[key])
                result[key] = desc
            elif not isinstance(result[key], str):
                result[key] = str(result[key])

        return result

    except Exception as e:
        # Fallback to basic template if AI fails
        build = build_data.build
        stats = build_data.playerStats
        return {
            "core_idea": f"{build.className} / {build.ascendClassName} 构建，等级 {build.level}。AI 生成失败: {e}",
            "core_items": "暂无数据",
            "budget_alternatives": "暂无数据",
            "talent_highlights": "暂无数据",
            "strength_review": "暂无数据",
        }
