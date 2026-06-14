from dataclasses import dataclass

from app.services.knowledge_guard import draft_mentions_game_facts, is_rag_exempt, should_force_rag

@dataclass
class _Ctx:
    rag_search_calls: int = 0

def test_trade_find_minion_amulet_not_forced() -> None:
    msg = '帮我找+2召唤项链'
    assert is_rag_exempt(msg) is True
    assert should_force_rag(msg, _Ctx()) is False

def test_affix_survival_question_forces_rag() -> None:
    msg = '除了+2还有哪些词缀增强召唤生存'
    assert should_force_rag(msg, _Ctx()) is True

def test_draft_recommended_affix_header() -> None:
    draft = '### 推荐词缀\n- +2 召唤技能等级'
    assert draft_mentions_game_facts(draft) is True

def test_no_force_after_rag_called() -> None:
    msg = '除了+2还有哪些词缀增强召唤生存'
    assert should_force_rag(msg, _Ctx(rag_search_calls=1)) is False
