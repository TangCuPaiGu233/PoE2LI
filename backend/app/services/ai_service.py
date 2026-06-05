"""AI service for generating build playbooks.

Currently returns mock data. Will be replaced with real AI calls
(DeepSeek V4 Flash or mimo-v2.5) when API keys are configured.
"""

from app.models.schemas import DecodeResponse


def generate_homework(build_data: DecodeResponse) -> dict:
    """Generate a Chinese playbook from BuildData.

    Returns a dict with five sections:
    - core_idea: Build philosophy and playstyle
    - core_items: Essential equipment
    - budget_alternatives: Cheaper substitutes
    - talent_highlights: Notable passive tree choices
    - strength_review: Build strengths and weaknesses
    """
    # Extract key info for the prompt
    build = build_data.build
    stats = build_data.playerStats
    tree = build_data.treeSpecs
    skills = build_data.skillSets

    # TODO: Replace with real AI call
    # For now, generate a structured response based on actual data
    class_name = build.className or "Unknown"
    ascendancy = build.ascendClassName or "None"
    level = build.level or "?"
    life = stats.get("Life", "N/A")
    dps = stats.get("TotalDPS", "N/A")
    node_count = sum(len(ts.nodes) for ts in tree)
    gem_count = sum(len(ss.gems) for ss in skills)

    # Build gem list
    gem_names = []
    for ss in skills:
        for g in ss.gems:
            if g.enabled and g.nameSpec:
                gem_names.append(g.nameSpec)

    gem_str = "、".join(gem_names[:6]) if gem_names else "未配置"

    return {
        "core_idea": (
            f"Level {level} {ascendancy if ascendancy != 'None' else ''}{class_name} build. "
            f"Core skill: {gem_str}. "
            f"Focus on balancing survival (Life {life}) and damage (DPS {dps})."
        ),
        "core_items": (
            "Core items:\n"
            "1. High physical damage weapon\n"
            "2. Life + resistance armor\n"
            "3. Damage-boosting accessories"
        ),
        "budget_alternatives": (
            "Budget alternatives:\n"
            "1. Weapon: lower damage but faster attack speed\n"
            "2. Armor: rare items with life + res, upgrade to uniques later\n"
            "3. Budget: 5-10 Divine Orb to start"
        ),
        "talent_highlights": (
            f"Tree uses {node_count} nodes. Key areas:\n"
            "1. Life nodes: survival first\n"
            "2. Damage nodes: core scaling\n"
            "3. Large jewel sockets"
        ),
        "strength_review": (
            f"Build assessment:\n"
            f"Strengths: {class_name} has strong base survival, efficient pathing\n"
            f"Weaknesses: gear-dependent, slow start\n"
            f"Rating: 7/10 (when geared)"
        ),
    }
