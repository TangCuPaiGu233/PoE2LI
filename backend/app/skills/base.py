"""base.py — Skill 基类。

每个 Skill 是一个独立的能力模块：有自己的检索策略、提示词、输出格式。
聊天路由根据意图分派到对应 Skill，Skill 之间互不耦合。
"""
from abc import ABC, abstractmethod


class BaseSkill(ABC):
    """聊天能力的抽象基类。"""

    name: str = "base"
    description: str = ""
    keywords: list[str] = []

    @abstractmethod
    def matches(self, query: str) -> bool:
        """判断用户意图是否匹配该 Skill。"""
        q = query.lower()
        return any(k in q for k in self.keywords)

    @abstractmethod
    def build_prompt(self, context: str, user_msg: str, **kwargs) -> str:
        """构建该 Skill 的系统提示词。"""

    def retrieve(self, query: str, q_embedding, top_k: int = 5, **kwargs) -> list[dict]:
        """默认检索：全源向量搜索。子类可覆盖实现专属检索策略。"""
        return []

    def get_chunk_types(self) -> list[str] | None:
        """返回该 Skill 感兴趣的 chunk_type 列表，用于预过滤。None = 不过滤。"""
        return None
