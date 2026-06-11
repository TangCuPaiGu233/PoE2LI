"""Tests for unified knowledge retrieval pipeline."""

import pytest

from app.services.retrieval_pipeline import (
    classify_intent,
    classify_question,
    find_concepts_in_query,
    is_reverse_lookup,
    build_search_query,
    chunk_text_for_context,
)


def test_classify_intent_reverse_lookup():
    q = "什么装备能提供召唤兽等级+2"
    assert classify_intent(q) == "reverse_lookup"


def test_classify_intent_encyclopedia():
    assert classify_intent("火球术是什么技能") == "encyclopedia"


def test_classify_intent_build_design():
    assert classify_intent("帮我配一套开荒BD") == "build_design"


def test_classify_question_includes_minion():
    types = classify_question("召唤兽有什么机制")
    assert "minion" in types
    assert "wiki" in types


def test_find_concepts_minion_skill_level():
    matches = find_concepts_in_query("召唤兽等级+2的装备")
    names = [n for n, _ in matches]
    assert "minion_skill_level" in names


def test_is_reverse_lookup_requires_trigger_and_concept():
    assert is_reverse_lookup("什么装备带召唤物等级+2") is True
    assert is_reverse_lookup("火球术是什么") is False
    assert is_reverse_lookup("什么装备比较好") is False


def test_build_search_query_combines_parts():
    q = build_search_query("问题", ["Fireball"], ["minion skill"])
    assert "问题" in q
    assert "Fireball" in q
    assert "minion skill" in q


def test_chunk_text_for_context_minion_limit():
    long_text = "x" * 5000
    c = {"content": long_text, "chunk_type": "minion", "source": "pob"}
    out = chunk_text_for_context(c)
    assert "[pob/minion]" in out
    assert len(out) < 4000


def test_chunk_text_for_context_instilled_notables_limit():
    import json

    body = "x" * 500 + "\n## Possible Instilled Notables\n" + "- Notable: effect\n" * 200
    c = {
        "content": json.dumps({"search_text": body}),
        "chunk_type": "item",
        "source": "poe2wiki",
    }
    out = chunk_text_for_context(c)
    assert "Possible Instilled Notables" in out
    assert len(out) > 1500
