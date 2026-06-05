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
            f"这是一个 {level} 级的 {ascendancy if ascendancy != 'None' else ''}{class_name} 构建。"
            f"主要使用 {gem_str} 作为核心技能。"
            f"整体思路是通过合理的天赋点分配和装备搭配，"
            f"在保证生存能力（生命 {life}）的前提下，"
            f"最大化输出伤害（DPS {dps}）。"
        ),
        "core_items": (
            "核心装备方面，该构建需要以下关键物品：\n"
            "1. 高物理解析武器（提升基础伤害）\n"
            "2. 生命 + 抗性防具（保证生存）\n"
            "3. 增伤辅助装备（手套、腰带等）\n"
            "具体装备请参考物品栏详细信息。"
        ),
        "budget_alternatives": (
            "预算替代方案：\n"
            "1. 武器：可用低物伤但攻速快的替代品过渡\n"
            "2. 防具：先用稀有装备堆生命和抗性，后期再换独特装备\n"
            "3. 珠宝：优先选择生命 + 伤害的稀有珠宝\n"
            "总体预算控制在 5-10 Divine Orb 以内可成型。"
        ),
        "talent_highlights": (
            f"天赋树共分配了 {node_count} 个节点，重点区域：\n"
            "1. 生命圈：优先保证生存能力\n"
            "2. 伤害圈：核心增伤节点\n"
            "3. 关键天赋：留意大型珠宝槽位\n"
            "建议先点生存，再补伤害。"
        ),
        "strength_review": (
            "构建强度评估：\n"
            f"优势：{class_name} 基础生存能力强，天赋路径高效\n"
            "劣势：对装备依赖度较高，成型前体验一般\n"
            "适用场景：适合中后期刷图和一般 Boss 战\n"
            "总体评分：7/10（成型后）"
        ),
    }
