"""Robust one-shot patch for chat_agent.py at 262a454 checkpoint.

Expects worktree file with:
- from app.services.llm_stream import emit_streamed_answer, first_choice, get_llm_client  (inline, line 20)
- _llm_client, _first_choice, _emit_streamed_answer  (already removed)
- Still has: _sanitize_answer (101), _sanitize_reasoning (119), _safe_flush_point (132)
- Still has: _TOOL_TAG_RE (151), _TOOL_TAG_CLOSE_RE (152)
- Still has: _filter_reasoning_chunk (154), _is_tool_call_only (207), _model (303)

Safe to run from worktree root (D:\PC_AI\Project\PoE2LI) or from backend/.
Idempotent — checks for alias import before patching.
"""
from pathlib import Path
import re

# Auto-detect correct path
candidates = [
    Path("backend/app/services/chat_agent.py"),
    Path("app/services/chat_agent.py"),
    Path("D:/PC_AI/Project/PoE2LI/backend/app/services/chat_agent.py"),
]
path = None
for p in candidates:
    if p.exists():
        path = p
        break
if not path:
    print("[FAIL] Cannot find chat_agent.py")
    exit(1)
print(f"[INFO] Patching: {path}")

text = path.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
orig_len = len(lines)

# === Step 1: Already patched? ===
if any("sanitize_answer as _sanitize_answer" in l for l in lines):
    print("[SKIP] Already fully patched (alias imports present)")
    exit(0)

# === Step 2: Replace inline import with aliased block ===
OLD = "from app.services.llm_stream import emit_streamed_answer, first_choice, get_llm_client"
NEW = """from app.services.llm_stream import (
    emit_streamed_answer,
    first_choice,
    get_llm_client,
    get_model as _model,
    sanitize_answer as _sanitize_answer,
    sanitize_reasoning as _sanitize_reasoning,
    safe_flush_point as _safe_flush_point,
    filter_reasoning_chunk as _filter_reasoning_chunk,
)
"""

replaced = False
for i, l in enumerate(lines):
    if OLD in l:
        lines[i] = NEW
        replaced = True
        print(f"[OK] Replaced inline import at line {i+1}")
        break
    if "from app.services.llm_stream import" in l:
        lines[i] = NEW
        replaced = True
        print(f"[OK] Replaced llm_stream import variant at line {i+1}")
        break
if not replaced:
    print("[FAIL] No llm_stream import found — unexpected file state")
    exit(1)

text = "".join(lines)
lines = text.splitlines(keepends=True)

# === Step 3: Remove duplicate function definitions + orphaned regex globals ===
# Strategy: mark line ranges [start, end) for each target, sort reverse, delete

def find_func_range(lines, func_name):
    """Find [start, end) for a top-level function definition."""
    for i, l in enumerate(lines):
        if l.lstrip().startswith(f"def {func_name}("):
            end = len(lines)
            for j in range(i + 1, len(lines)):
                s = lines[j]
                if re.match(r'^(async\s+)?def\s+\w+\(', s):
                    end = j
                    break
                if s.strip() and not s[0].isspace() and not s.startswith('@') and not s.startswith('#'):
                    end = j
                    break
            return (i, end)
    return None

def find_regex_line(lines, var_name):
    """Find a single top-level regex assignment line."""
    for i, l in enumerate(lines):
        if l.lstrip().startswith(f"{var_name} = re.compile("):
            return (i, i + 1)
    return None

targets = [
    "_sanitize_answer",
    "_sanitize_reasoning",
    "_safe_flush_point",
    "_filter_reasoning_chunk",
    "_is_tool_call_only",
    "_model",
]

ranges = []
for name in targets:
    r = find_func_range(lines, name)
    if r:
        ranges.append(r)
        print(f"[OK] Mark {name}: lines {r[0]+1}-{r[1]}")

# Remove orphaned regex globals
for vn in ["_TOOL_TAG_RE", "_TOOL_TAG_CLOSE_RE"]:
    r = find_regex_line(lines, vn)
    if r:
        ranges.append(r)
        print(f"[OK] Mark {vn}: line {r[0]+1}")

ranges.sort(reverse=True)
for start, end in ranges:
    del lines[start:end]

final_text = "".join(lines)
path.write_text(final_text, encoding="utf-8")

final_len = len(lines)
print(f"\n[DONE] {orig_len} → {final_len} lines ({final_len - orig_len} delta)")
print()
print("[VERIFY] Now run:")
print("  cd backend && python -c \"from app.services.chat_agent import stream_chat_agent; print('IMPORT OK')\"")
