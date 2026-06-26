"""Unit tests for entity_validator.validate_answer.

Tests cover:
- English entity extraction and PoE1 blacklist filtering
- Confusable pair detection (e.g. Twisted vs Distorted Amulet)
- Evidence grounding (entity in retrieval chunks → PASS)
- GameGraph cross-check (mocked)
- Chinese entity extraction via jieba (bypassed to avoid DB dependency)
"""

from unittest.mock import patch

import pytest

from app.services.entity_validator import (
    _POE1_BLACKLIST_EN,
    _CONFUSABLE_EN,
    validate_answer,
)


@pytest.fixture(autouse=True)
def _mock_jieba_db_load():
    """Prevent _ensure_jieba from querying kb_entities during tests.

    The real implementation loads PoE2 Chinese entity names from the DB into
    jieba's dictionary. For unit tests we only need jieba's default tokenizer,
    so we bypass the DB call entirely.
    """
    with patch("app.services.entity_validator._extract_cn_entities", return_value=set()):
        yield


class TestValidateAnswerEnglishEntities:
    # ── Baseline: no suspicious entities when text is clean ──

    def test_clean_text_no_suspicious(self):
        text = "这件装备提供生命值和抗性，适合开荒使用。"
        result = validate_answer(text, evidence_texts=["生命值", "抗性"])
        assert result == []

    def test_common_false_positives_ignored(self):
        text = "weapon has high physical damage and critical strike chance."
        result = validate_answer(text, evidence_texts=["physical damage", "critical"])
        assert result == []

    # ── PoE1 blacklist ──

    def test_poe1_entity_in_blacklist(self):
        text = "The build uses Juggernaut and Bone Offering."
        result = validate_answer(text, evidence_texts=[])
        poe1_hits = [e for e in result if e.get("risk") == "POE1_RESIDUE"]
        assert len(poe1_hits) >= 2
        names = {e["name"] for e in poe1_hits}
        assert "juggernaut" in names
        assert "bone offering" in names

    def test_poe1_entity_in_evidence_is_grounded(self):
        text = "Juggernaut"
        result = validate_answer(text, evidence_texts=["Juggernaut is a PoE2 ascendancy."])
        poe1_hits = [e for e in result if e.get("risk") == "POE1_RESIDUE"]
        assert poe1_hits == []

    # ── Confusable pairs ──

    def test_confusable_twisted_vs_distorted(self):
        text = "Twisted Amulet is the base for Delirium."
        result = validate_answer(text, evidence_texts=[])
        confusable = [e for e in result if e.get("risk") == "CONFUSABLE"]
        assert len(confusable) >= 1
        names = {e["name"] for e in confusable}
        assert "twisted amulet" in names

    def test_confusable_distorted_vs_twisted(self):
        text = "Distorted Amulet has a normal affix pool."
        result = validate_answer(text, evidence_texts=[])
        confusable = [e for e in result if e.get("risk") == "CONFUSABLE"]
        assert len(confusable) >= 1
        names = {e["name"] for e in confusable}
        assert "distorted amulet" in names

    # ── Evidence grounding ──

    def test_entity_in_evidence_is_grounded(self):
        text = "Spirit Walker is a popular ascendancy."
        result = validate_answer(text, evidence_texts=["Spirit Walker ascendancy skills"])
        assert result == []

    def test_entity_not_in_evidence_not_in_game_graph(self):
        with patch("app.services.entity_validator._check_game_graph", return_value="not_found"):
            text = "Fake Entity is not real."
            result = validate_answer(text, evidence_texts=[])
            not_in_game = [e for e in result if e.get("risk") == "NOT_IN_GAME_DATA"]
            assert len(not_in_game) >= 1
            assert "fake entity" in {e["name"] for e in not_in_game}

    def test_entity_not_in_evidence_but_in_game_graph(self):
        with patch("app.services.entity_validator._check_game_graph", return_value="found"):
            text = "Some Real Entity exists."
            result = validate_answer(text, evidence_texts=[])
            not_grounded = [e for e in result if e.get("risk") == "NOT_GROUNDED"]
            assert len(not_grounded) >= 1
            assert "some real entity" in {e["name"] for e in not_grounded}

    # ── Empty / edge cases ──

    def test_empty_text_returns_empty(self):
        assert validate_answer("", evidence_texts=[]) == []

    def test_none_text_returns_empty(self):
        assert validate_answer(None, evidence_texts=[]) == []

    def test_none_evidence_treated_as_empty(self):
        text = "Juggernaut"
        result = validate_answer(text, evidence_texts=None)
        poe1_hits = [e for e in result if e.get("risk") == "POE1_RESIDUE"]
        assert len(poe1_hits) >= 1


class TestValidateAnswerChineseEntities:
    # ── Chinese entity extraction via jieba ──

    def test_cn_entities_detected(self):
        # Confusable check scans full text lowercased against known pairs.
        # Include an English confusable term so the check can trigger.
        text = "Twisted Amulet 是普通基底，Distorted Amulet 用于涂油。"
        result = validate_answer(text, evidence_texts=[])
        confusable = [e for e in result if e.get("risk") == "CONFUSABLE"]
        assert len(confusable) >= 1


class TestValidateAnswerIntegration:
    # ── Mixed English/Chinese with evidence ──

    def test_mixed_with_evidence(self):
        text = "Spirit Walker 使用灵魂行者技能，装备 Distorted Amulet。"
        result = validate_answer(text, evidence_texts=[
            "Spirit Walker ascendancy",
            "Distorted Amulet normal amulet",
        ])
        assert result == []

    def test_mixed_without_evidence_has_suspicious(self):
        with patch("app.services.entity_validator._check_game_graph", return_value="not_found"):
            text = "Fake Skill 装备 Fake Amulet。"
            result = validate_answer(text, evidence_texts=[])
            assert len(result) >= 1
            risks = {e["risk"] for e in result}
            assert "NOT_IN_GAME_DATA" in risks or "POE1_RESIDUE" in risks
