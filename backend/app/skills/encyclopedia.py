"""encyclopedia.py — 百科问答 Skill。工具: rag_search / entity_resolve。"""
from app.skills.base import BaseSkill


class EncyclopediaSkill(BaseSkill):
    name = "encyclopedia"
    description = "回答 PoE2 机制、技能效果、物品属性等知识类问题"
    tools = ["rag_search", "entity_resolve", "keyword_correct"]
    keywords = [
        "是什么", "什么是", "什么意思", "怎么用", "机制", "效果",
        "多少", "怎么算", "公式", "数据", "属性", "怎么得",
        "有哪些", "有什么", "介绍一下", "怎么样",
    ]

    def matches(self, query: str) -> bool:
        q = query.lower()
        return any(k in q for k in self.keywords)

    def system_prompt(self, **kwargs) -> str:
        asc_en = kwargs.get("asc_en", "")
        asc_cn = kwargs.get("asc_cn", "")
        context = kwargs.get("context", "")

        parts = ["你是 PoE2 百科助手。基于资料回答, 不要编造。\n"]
        if asc_en:
            parts.append(
                "用户询问的升华是 " + str(asc_cn) + "(" + str(asc_en) + ")。"
                "只回答该升华的信息, 绝不用其他升华资料替代。\n"
            )
        parts.extend([
            "规则:\n",
            "1. 先一句话直接回答\n",
            "2. 有详细数据就列表展开\n",
            "3. 资料不足就诚实说明\n",
            "4. 保持简洁\n\n",
            "资料:\n", context,
        ])
        return "".join(parts)
