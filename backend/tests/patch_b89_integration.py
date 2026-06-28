import pathlib

p = pathlib.Path('tests/unit/test_chat_guard.py')
text = p.read_text(encoding='utf-8')

# Append integration tests for B.8-B.9 in chat_agent.py / chat_tools.py
append_block = '''

# ── B.8/B.9 integration: chat_agent + chat_tools ────────────────────


def test_consecutive_failures_abort_after_three(monkeypatch):
    from app.services.chat_agent import stream_chat_agent
    from app.services.chat_tools import ChatToolContext

    events = []

    class FakeChunk:
        def __init__(self, content="done"):
            self.choices = [
                type("Choice", (), {"delta": type("Delta", (), {"content": content})})()
            ]

    class FakeStream:
        def __init__(self):
            self._chunks = [FakeChunk("done")]
            self._i = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._i < len(self._chunks):
                chunk = self._chunks[self._i]
                self._i += 1
                return chunk
            raise StopAsyncIteration

    class FakeCompletions:
        async def create(self, *args, **kwargs):
            events.append("llm_call")
            return FakeStream()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

    fake = FakeClient()
    monkeypatch.setattr("app.services.chat_agent.get_llm_client", lambda: fake)
    monkeypatch.setattr("app.services.chat_orchestrator.get_llm_client", lambda: fake)
    monkeypatch.setattr("app.services.chat_orchestrator.generate_follow_up_questions", lambda *a, **k: None)
    monkeypatch.setattr("app.services.chat_orchestrator.validate_answer", lambda *a, **k: [])
    monkeypatch.setattr("app.services.chat_orchestrator.flush", lambda: None)

    call_counter = {"count": 0}

    async def fake_execute(name, args, ctx):
        call_counter["count"] += 1
        from app.services.chat_tools import ToolRunResult
        raise RuntimeError("tool failure")

    import app.services.chat_agent as chat_agent_mod
    import app.services.chat_tools as chat_tools_mod
    monkeypatch.setattr(chat_agent_mod.execute_tool, fake_execute)
    monkeypatch.setattr(chat_tools_mod.execute_tool, fake_execute)

    async def run():
        async for ev in stream_chat_agent([{"role": "user", "content": "test"}]):
            events.append(ev)

    import asyncio
    asyncio.run(run())
    assert call_counter["count"] == 3
    assert any("工具连续失败" in str(ev.get("content", "")) for ev in events)


def test_decode_pob_abort_after_two(monkeypatch):
    from app.services.chat_agent import stream_chat_agent
    from app.services.chat_tools import ChatToolContext

    events = []

    class FakeChunk:
        def __init__(self, content="done"):
            self.choices = [
                type("Choice", (), {"delta": type("Delta", (), {"content": content})})()
            ]

    class FakeStream:
        def __init__(self):
            self._chunks = [FakeChunk("done")]
            self._i = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._i < len(self._chunks):
                chunk = self._chunks[self._i]
                self._i += 1
                return chunk
            raise StopAsyncIteration

    class FakeCompletions:
        async def create(self, *args, **kwargs):
            events.append("llm_call")
            return FakeStream()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

    fake = FakeClient()
    monkeypatch.setattr("app.services.chat_agent.get_llm_client", lambda: fake)
    monkeypatch.setattr("app.services.chat_orchestrator.get_llm_client", lambda: fake)
    monkeypatch.setattr("app.services.chat_orchestrator.generate_follow_up_questions", lambda *a, **k: None)
    monkeypatch.setattr("app.services.chat_orchestrator.validate_answer", lambda *a, **k: [])
    monkeypatch.setattr("app.services.chat_orchestrator.flush", lambda: None)

    call_counter = {"count": 0}

    async def fake_execute(name, args, ctx):
        call_counter["count"] += 1
        from app.services.chat_tools import ToolRunResult
        raise RuntimeError("pob failure")

    import app.services.chat_agent as chat_agent_mod
    import app.services.chat_tools as chat_tools_mod
    monkeypatch.setattr(chat_agent_mod.execute_tool, fake_execute)
    monkeypatch.setattr(chat_tools_mod.execute_tool, fake_execute)

    async def run():
        messages = [
            {"role": "user", "content": "test"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "decode_pob", "arguments": '{"input":"eN1"}'}}
            ]},
        ]
        async for ev in stream_chat_agent(messages):
            events.append(ev)

    import asyncio
    asyncio.run(run())
    assert call_counter["count"] == 2
    assert any("工具连续失败" in str(ev.get("content", "")) for ev in events)


def test_tool_call_history_blocks_repeated_loop(monkeypatch):
    from app.services.chat_tools import ChatToolContext, execute_tool

    ctx = ChatToolContext(user_msg="test")

    async def fake_entity_resolve(args, ctx):
        from app.services.chat_tools import ToolRunResult
        return ToolRunResult(content="ok")

    import app.services.chat_tools as chat_tools_mod
    monkeypatch.setattr(chat_tools_mod, "_run_entity_resolve", fake_entity_resolve)

    async def run():
        await execute_tool("entity_resolve", {"text": "a"}, ctx)
        await execute_tool("entity_resolve", {"text": "a"}, ctx)
        return await execute_tool("entity_resolve", {"text": "a"}, ctx)

    import asyncio
    result = asyncio.run(run())
    assert "repeated_tool_loop" in result.content
    assert len(ctx.tool_call_history) == 3


def test_trade_search_similar_query_detected(monkeypatch):
    from app.services.chat_tools import ChatToolContext, execute_tool

    ctx = ChatToolContext(user_msg="test")

    async def fake_trade(args, ctx):
        from app.services.chat_tools import ToolRunResult
        return ToolRunResult(content="ok", trade_result={"best_match": {"label": "x"}})

    import app.services.chat_tools as chat_tools_mod
    monkeypatch.setattr(chat_tools_mod, "_run_trade_search", fake_trade)

    async def run():
        await execute_tool("trade_search", {"query": "法师之血 腰带"}, ctx)
        return await execute_tool("trade_search", {"query": "腰带 法师之血"}, ctx)

    import asyncio
    result = asyncio.run(run())
    assert "similar_trade_query" in result.content
'''

if 'def test_consecutive_failures_abort_after_three' not in text:
    p.write_text(text + append_block, encoding='utf-8')
    print('APPENDED_B89_TESTS')
else:
    print('B89_TESTS_ALREADY_PRESENT')
