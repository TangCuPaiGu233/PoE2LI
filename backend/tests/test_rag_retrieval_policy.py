"""Tests for unified RAG retrieval policy."""

from app.services.rag_retrieval_policy import (
    build_rag_options,
    classify_retrieval_intent,
    retrieval_top_k,
    structured_fetch_mode,
)


def test_catalog_intent_keywords():
    assert classify_retrieval_intent("灵魂行者有哪些升华技能") == "catalog"
    assert classify_retrieval_intent("火球术是什么技能") == "detail"


def test_structured_fetch_mode_by_intent_not_entity_whitelist():
    assert structured_fetch_mode("skill", "detail") == "single"
    assert structured_fetch_mode("skill", "catalog") == "multi"
    assert structured_fetch_mode("ascendancy", "detail") == "multi"


def test_top_k_catalog_and_ascendancy():
    assert retrieval_top_k(intent="catalog", entity_types=set(), fast=True) == 14
    assert retrieval_top_k(intent="detail", entity_types={"ascendancy"}, fast=True) == 14
    assert retrieval_top_k(intent="detail", entity_types={"skill"}, fast=True) == 5


def test_build_rag_options_fast_skips_multi_source():
    opts, intent = build_rag_options(
        user_msg="火球术是什么",
        query="火球术",
        entities=[],
        fast=True,
        q_embedding=[0.1],
        league=None,
        game_version=None,
        alias_keywords=[],
    )
    assert intent == "detail"
    assert opts.multi_source is False
    assert opts.top_k == 5
