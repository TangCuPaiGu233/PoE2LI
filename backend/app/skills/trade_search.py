"""trade_search.py — 装备搜索 Skill。

调用 Trade API 搜索交易市场，返回装备链接和价格信息。
不走 RAG 检索，直接调 trade_agent.run_agent()。
"""
import json
import logging
from app.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class TradeSearchSkill(BaseSkill):
    name = "trade_search"
    description = "搜索 PoE2 交易市场，查找装备、比较价格"
    keywords = [
        "搜", "找装备", "买", "卖", "价格", "交易", "搜索",
        "帮我找", "帮我搜", "搜一下", "查一下价格", "多少钱",
        "市价", "集市", "trade",
    ]

    def matches(self, query: str) -> bool:
        q = query.lower()
        return any(k in q for k in self.keywords)

    def build_prompt(self, context: str, user_msg: str, **kwargs) -> str:
        trade_result = kwargs.get("trade_result", {})
        best = trade_result.get("best_match")
        alts = trade_result.get("alternatives", [])
        explanation = trade_result.get("explanation", "")

        return (
            "你是 PoE2 交易助手。用户搜索了装备, 以下是搜索结果。"
            "用中文简要说明找到了什么、为什么匹配、推荐哪个方案。\n\n"
            "用户查询: " + user_msg + "\n\n"
            "最佳匹配: " + json.dumps(best, ensure_ascii=False) + "\n"
            "其他选择: " + json.dumps(alts[:3], ensure_ascii=False) + "\n"
            "搜索说明: " + explanation + "\n"
        )

    def get_chunk_types(self) -> list[str] | None:
        return None  # 不走 RAG，直接调 trade API
