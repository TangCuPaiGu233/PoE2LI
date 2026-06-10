"""trade_search.py — 装备搜索 Skill。工具: trade_api / entity_resolve。"""
import json
from app.skills.base import BaseSkill


class TradeSearchSkill(BaseSkill):
    name = "trade_search"
    description = "搜索 PoE2 交易市场，查找装备、比较价格"
    tools = ["trade_api", "entity_resolve"]
    keywords = [
        "搜", "找装备", "买", "卖", "价格", "交易",
        "帮我找", "帮我搜", "搜一下", "查一下价格", "多少钱",
        "市价", "集市", "trade",
    ]

    def matches(self, query: str) -> bool:
        q = query.lower()
        return any(k in q for k in self.keywords)

    def system_prompt(self, **kwargs) -> str:
        trade_result = kwargs.get("trade_result", {})
        user_msg = kwargs.get("user_msg", "")
        best = trade_result.get("best_match")
        alts = trade_result.get("alternatives", [])

        return (
            "你是 PoE2 交易助手。帮用户理解搜索结果。\n\n"
            "用户查询: " + user_msg + "\n\n"
            "最佳匹配: " + json.dumps(best, ensure_ascii=False) + "\n"
            "其他选择: " + json.dumps(alts[:3], ensure_ascii=False) + "\n"
            "搜索说明: " + trade_result.get("explanation", "") + "\n"
        )
