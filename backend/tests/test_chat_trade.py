import pytest
from unittest.mock import patch, MagicMock
from app.services.ai_service import chat_about_build
from app.models.build import Build

@pytest.fixture
def mock_build():
    build = MagicMock(spec=Build)
    build.id = 1
    build.league = "Standard"
    build.game_version = "v1"
    build.class_name = "Witch"
    build.ascendancy = "Elementalist"
    build.level = 90
    build.get_build_data.return_value = {}
    build.get_homework.return_value = {}
    return build

@patch('app.services.trade_service.trade_search')
@patch('app.services.ai_service.get_llm_client')
@patch('app.services.ai_service.SessionLocal')
@patch('app.services.knowledge_service.retrieve_similar')
def test_chat_about_build_with_trade_intent(mock_retrieve, mock_session, mock_get_client, mock_trade_search, mock_build):
    mock_chat_create = mock_get_client.return_value.chat.completions.create
    # Setup RAG mocks
    mock_retrieve.return_value = []
    
    # Mock LLM to detect trade intent
    mock_chat_response = MagicMock()
    mock_chat_response.choices[0].message.content = '{"trade_intent": "加2召唤兽等级的项链", "response": "没问题，我来帮你找。"}'
    mock_chat_create.return_value = mock_chat_response
    
    # Mock trade search
    mock_trade_search.return_value = {
        "trade_url": "https://www.pathofexile.com/trade2/search/poe2/Standard/12345",
        "total_results": 157
    }
    
    # Run chat
    answer = chat_about_build(mock_build, "帮我找一条加2召唤兽等级的项链")
    
    # Verify trade_search was called
    mock_trade_search.assert_called_once_with("加2召唤兽等级的项链", "Standard")
    
    # Verify answer includes the trade URL
    assert "https://www.pathofexile.com/trade2/search/poe2/Standard/12345" in answer
    assert "没问题，我来帮你找" in answer

@patch('app.services.trade_service.trade_search')
@patch('app.services.ai_service.get_llm_client')
@patch('app.services.ai_service.SessionLocal')
@patch('app.services.knowledge_service.retrieve_similar')
def test_chat_about_build_without_trade_intent(mock_retrieve, mock_session, mock_get_client, mock_trade_search, mock_build):
    mock_chat_create = mock_get_client.return_value.chat.completions.create
    # Setup RAG mocks
    mock_retrieve.return_value = []
    
    # Mock LLM without trade intent
    mock_chat_response = MagicMock()
    # It might just return text or a JSON without trade_intent
    mock_chat_response.choices[0].message.content = "这个 BD 主要靠召唤物打伤害。"
    mock_chat_create.return_value = mock_chat_response
    
    # Run chat
    answer = chat_about_build(mock_build, "这个BD怎么打伤害？")
    
    # Verify trade_search was NOT called
    mock_trade_search.assert_not_called()
    
    # Verify normal answer
    assert "主要靠召唤物打伤害" in answer
