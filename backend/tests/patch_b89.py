import pathlib

chat_agent = pathlib.Path('app/services/chat_agent.py')
chat_tools = pathlib.Path('app/services/chat_tools.py')

agent_text = chat_agent.read_text(encoding='utf-8')
tools_text = chat_tools.read_text(encoding='utf-8')

# ── chat_agent.py: consecutive failure counter + abort ──
agent_anchor = '''            except Exception as e:
                logger.error("[CHAT] tool %s failed: %s", fn, e)
                result_content = json.dumps({"error": str(e)}, ensure_ascii=False)
                yield {
                    "type": "tool_result",
                    "content": {"name": fn, "ok": False, "preview": str(e)[:200]},
                }
                agent_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_content,
                    },
                )
                continue
'''

agent_replacement = '''            except Exception as e:
                logger.error("[CHAT] tool %s failed: %s", fn, e)
                ctx.consecutive_failures += 1
                result_content = json.dumps({"error": str(e)}, ensure_ascii=False)
                yield {
                    "type": "tool_result",
                    "content": {"name": fn, "ok": False, "preview": str(e)[:200]},
                }
                agent_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_content,
                    },
                )
                if (fn == "decode_pob" and ctx.consecutive_failures >= 2) or ctx.consecutive_failures >= 3:
                    yield {
                        "type": "thinking",
                        "content": f"工具连续失败 {ctx.consecutive_failures} 次，已中止工具循环，转为综合回答。",
                    }
                    break
                continue
'''

if agent_anchor not in agent_text:
    print('AGENT_ANCHOR_NOT_FOUND')
    raise SystemExit(1)
agent_text = agent_text.replace(agent_anchor, agent_replacement)

# Reset consecutive failures after successful tool execution, before appending tool message.
agent_success_anchor = '''            preview = result.content[:240] + ("..." if len(result.content) > 240 else "")
            yield {
                "type": "tool_result",
                "content": {"name": fn, "ok": True, "preview": preview},
            }

            if result.trade_result:
                yield {"type": "trade_result", "content": result.trade_result}
                if isinstance(result.trade_result, dict) and result.trade_result.get("listing_price"):
                    _had_listing_price = True
            if result.recommend_result:
                yield {"type": "recommend_result", "content": result.recommend_result}

            agent_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.content,
                },
            )
'''

agent_success_replacement = '''            ctx.consecutive_failures = 0
            preview = result.content[:240] + ("..." if len(result.content) > 240 else "")
            yield {
                "type": "tool_result",
                "content": {"name": fn, "ok": True, "preview": preview},
            }

            if result.trade_result:
                yield {"type": "trade_result", "content": result.trade_result}
                if isinstance(result.trade_result, dict) and result.trade_result.get("listing_price"):
                    _had_listing_price = True
            if result.recommend_result:
                yield {"type": "recommend_result", "content": result.recommend_result}

            agent_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.content,
                },
            )
'''

if agent_success_anchor not in agent_text:
    print('AGENT_SUCCESS_ANCHOR_NOT_FOUND')
    raise SystemExit(1)
agent_text = agent_text.replace(agent_success_anchor, agent_success_replacement)

chat_agent.write_text(agent_text, encoding='utf-8')
print('PATCHED_CHAT_AGENT_B8')

# ── chat_tools.py: tool_call_history + cross-turn loop detection ──
tools_anchor = '''    logger.info("[CHAT] tool_call name=%s args=%s", name, str(args)[:200])
    timeout = float(os.getenv("CHAT_TOOL_TIMEOUT_SEC", "45"))
'''

tools_replacement = '''    logger.info("[CHAT] tool_call name=%s args=%s", name, str(args)[:200])
    ctx.tool_call_history.append({"name": name, "args": args})
    timeout = float(os.getenv("CHAT_TOOL_TIMEOUT_SEC", "45"))
'''

if tools_anchor not in tools_text:
    print('TOOLS_ANCHOR_NOT_FOUND')
    raise SystemExit(1)
tools_text = tools_text.replace(tools_anchor, tools_replacement)

# Insert cross-turn repeated tool+params detection after timeout line
loop_anchor = '''    timeout = float(os.getenv("CHAT_TOOL_TIMEOUT_SEC", "45"))
    if name == "entity_resolve":
'''

loop_replacement = '''    timeout = float(os.getenv("CHAT_TOOL_TIMEOUT_SEC", "45"))
    recent = [entry for entry in ctx.tool_call_history[-6:] if entry.get("name") == name]
    if len(recent) >= 3:
        seen = [tuple(sorted((entry.get("args") or {}).items())) for entry in recent]
        if seen[0] and all(s == seen[0] for s in seen):
            return ToolRunResult(
                content=json.dumps(
                    {
                        "status": "blocked",
                        "reason": "repeated_tool_loop",
                        "hint": f"{name} 已在近期重复调用且参数完全相同，已跳过。请基于已有结果综合回答。",
                    },
                    ensure_ascii=False,
                ),
            )
    if name == "trade_search":
        query = str(args.get("query") or "").strip()
        prev_queries = [str(entry.get("args", {}).get("query") or "") for entry in ctx.tool_call_history[-6:] if entry.get("name") == "trade_search"]
        prev_queries = [q for q in prev_queries if q]
        if prev_queries:
            def _jw(a: str, b: str) -> float:
                sa, sb = set(a.lower().split()), set(b.lower().split())
                u = len(sa | sb)
                return len(sa & sb) / u if u else 0.0
            if any(_jw(query, q) > 0.72 for q in prev_queries[:-1]):
                return ToolRunResult(
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "reason": "similar_trade_query",
                            "hint": "当前 trade_search query 与近期搜索过于相似，已跳过。请尝试不同角度或词缀。",
                        },
                        ensure_ascii=False,
                    ),
                )
    if name == "entity_resolve":
'''

if loop_anchor not in tools_text:
    print('LOOP_ANCHOR_NOT_FOUND')
    raise SystemExit(1)
tools_text = tools_text.replace(loop_anchor, loop_replacement)

chat_tools.write_text(tools_text, encoding='utf-8')
print('PATCHED_CHAT_TOOLS_B89')
