"""router.py — Skill 路由器。

根据用户输入匹配最合适的 Skill，按优先级：
  1. trade_search (搜装备/交易)
  2. build_design (配BD/构建)
  3. encyclopedia (默认兜底)
"""
from app.skills.base import BaseSkill
from app.skills.build_design import BuildDesignSkill
from app.skills.encyclopedia import EncyclopediaSkill
from app.skills.trade_search import TradeSearchSkill

# 注册所有 Skill（优先级从高到低）
SKILLS: list[BaseSkill] = [
    TradeSearchSkill(),
    BuildDesignSkill(),
    EncyclopediaSkill(),
]


def route(query: str) -> BaseSkill:
    """根据用户输入匹配最适合的 Skill。返回优先级最高的匹配。"""
    for skill in SKILLS:
        if skill.matches(query):
            return skill
    return SKILLS[-1]  # 默认 encyclopedia


def get_skill(name: str) -> BaseSkill | None:
    """按名称查找 Skill。"""
    for skill in SKILLS:
        if skill.name == name:
            return skill
    return None
