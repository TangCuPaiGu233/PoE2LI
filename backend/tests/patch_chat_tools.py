import pathlib

p = pathlib.Path('app/services/chat_tools.py')
text = p.read_text(encoding='utf-8')

old_block = '''    rag_queries: list[str] = field(default_factory=list)  # dedup: track all rag queries this turn
    last_chunks: list[str] = field(default_factory=list)  # evidence for entity validation
    last_game_searches: list[dict] = field(default_factory=list)  # game graph searches for validation
'''

new_block = '''    rag_queries: list[str] = field(default_factory=list)  # dedup: track all rag queries this turn
    last_chunks: list[str] = field(default_factory=list)  # evidence for entity validation
    last_game_searches: list[dict] = field(default_factory=list)  # game graph searches for validation
    consecutive_failures: int = 0
    tool_call_history: list[dict] = field(default_factory=list)
'''

if old_block not in text:
    print('OLD_BLOCK_NOT_FOUND')
    for i, line in enumerate(text.splitlines(), 1):
        if 'ChatToolContext' in line or 'rag_queries' in line:
            print(i, repr(line))
else:
    p.write_text(text.replace(old_block, new_block), encoding='utf-8')
    print('PATCHED_CHAT_TOOLS')
