"""recommend.py — 装备/物品对比推荐 Skill。工具: recommend_agent。"""
from app.skills.base import BaseSkill


class RecommendSkill(BaseSkill):
    name = "recommend"
    description = "对比多个装备或物品，给出个性化推荐排序"
    tools = ["recommend_agent", "entity_resolve"]
    keywords = [
        "哪个最适合", "哪个好", "推荐", "选哪个", "哪个更", "对比",
        "适不适合", "值不值得", "该用", "用哪", "比较",
    ]

    def matches(self, query: str) -> bool:
        return any(k in query for k in self.keywords)

    def system_prompt(self, **kwargs) -> str:
        context = kwargs.get("context", "")
        user_msg = kwargs.get("user_msg", "")
        return (
            "你是 PoE2 装备推荐专家。基于已完成的推荐分析结果回答用户。\n"
            "1. 先给出明确首选结论\n"
            "2. 简要对比各候选项优劣\n"
            "3. 如有预算语境，区分性价比与毕业选项\n\n"
            f"用户问题: {user_msg}\n\n"
            f"分析资料:\n{context}"
        )
