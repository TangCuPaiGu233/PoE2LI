"""Tests for fast RAG profile used by orchestrator sub-agents."""

from unittest.mock import patch

from app.services.chat_tools import ChatToolContext, _run_rag_search
from app.services.retrieval_pipeline import RetrievalResult


def test_rag_search_fast_disables_multi_source():
    captured: list = []

    def fake_dual(orig, rew, options=None):
        captured.append(options)
        return RetrievalResult(
            chunks=[
                {
                    "id": 1,
                    "content": "Fireball skill",
                    "chunk_type": "skill",
                    "source": "poe2db",
                    "similarity": 0.9,
                },
            ],
            intent="encyclopedia",
            search_query=rew,
        )

    ctx = ChatToolContext(user_msg="火球术是什么技能")
    with (
        patch("app.services.chat_tools.extract_alias_keywords", return_value=([], [])),
        patch("app.services.chat_tools.get_embedding", return_value=[0.1] * 1024),
        patch("app.services.chat_tools.retrieve_dual_path", side_effect=fake_dual),
        patch("app.services.chat_tools.expand_concepts") as mock_expand,
    ):
        result = _run_rag_search({"query": "火球术", "fast": True}, ctx)

    assert captured
    assert captured[0].multi_source is False
    mock_expand.assert_not_called()
    payload = __import__("json").loads(result.content)
    assert payload.get("fast") is True


def test_rag_search_catalog_uses_higher_top_k():
    captured: list = []

    def fake_dual(orig, rew, options=None):
        captured.append(options)
        return RetrievalResult(chunks=[], intent="encyclopedia", search_query=rew)

    ctx = ChatToolContext(user_msg="灵魂行者有哪些升华技能")
    with (
        patch(
            "app.services.chat_tools.extract_alias_keywords",
            return_value=(["Spirit Walker"], [("ascendancy", "Spirit Walker", "asc_nodes")]),
        ),
        patch("app.services.chat_tools.get_embedding", return_value=[0.1] * 1024),
        patch("app.services.chat_tools.retrieve_dual_path", side_effect=fake_dual),
        patch("app.services.chat_tools.structured_entity_lookup", return_value=[]),
    ):
        _run_rag_search({"query": "灵魂行者", "fast": True}, ctx)

    assert captured
    assert captured[0].top_k >= 14


def test_rag_search_always_uses_vector_path_for_skill_entity():
    ctx = ChatToolContext(user_msg="火球是什么技能")
    with (
        patch(
            "app.services.chat_tools.extract_alias_keywords",
            return_value=(["Fireball"], [("skill", "Fireball", "skill")]),
        ),
        patch("app.services.chat_tools.get_embedding", return_value=[0.1] * 1024) as mock_embed,
        patch(
            "app.services.chat_tools.retrieve_dual_path",
            return_value=RetrievalResult(
                chunks=[{"id": 1, "content": "x", "chunk_type": "skill", "source": "poe2db"}],
                intent="encyclopedia",
                search_query="q",
            ),
        ),
        patch("app.services.chat_tools.structured_entity_lookup", return_value=[]),
    ):
        _run_rag_search({"query": "火球", "fast": True}, ctx)

    mock_embed.assert_called_once()
