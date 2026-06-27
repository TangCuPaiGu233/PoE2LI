"""Robust one-shot patch: replace duplicate functions in chat_agent.py with llm_stream imports.

Reads chat_agent.py, applies precise line-based transformations, writes result.
Safe to run multiple times — idempotent.
"""
import re

PATH = "backend/app/services/chat_agent.py"

with open(PATH, encoding="utf-8") as f:
    lines = f.readlines()

# === Step 1: Check if already patched ===
already_patched = any("from app.services.llm_stream import" in l for l in lines)
if already_patched:
    print("[SKIP] chat_agent.py already has llm_stream import — no changes needed.")
    # Still verify and update orchestrator import if needed
else:
    print(f"[INFO] chat_agent.py: {len(lines)} lines, not yet patched.")

# === Step 2: Identify key markers ===
# Find the logger line (insertion point for import)
logger_idx = None
for i, line in enumerate(lines):
    if 'logger = logging.getLogger(__name__)' in line:
        logger_idx = i
        break

if logger_idx is None:
    raise RuntimeError("Cannot find logger line — file structure may differ from expected")

# === Step 3: Build the import block ===
import_block = [
    "\n",
    "from app.services.llm_stream import (\n",
    "    sanitize_answer as _sanitize_answer,\n",
    "    sanitize_reasoning as _sanitize_reasoning,\n",
    "    safe_flush_point as _safe_flush_point,\n",
    "    filter_reasoning_chunk as _filter_reasoning_chunk,\n",
    "    is_tool_call_only as _is_tool_call_only,\n",
    "    get_llm_client as _llm_client,\n",
    "    get_model as _model,\n",
    "    first_choice as _first_choice,\n",
    "    emit_streamed_answer as _emit_streamed_answer,\n",
    ")\n",
]

# Insert after logger line
lines[logger_idx+1:logger_idx+1] = import_block
print(f"[OK] Inserted llm_stream import block after line {logger_idx+1}")

# === Step 4: Remove private duplicate function definitions ===
# Strategy: find by 'def _xxx(' signature, remove until we hit next 'def' or end-of-module-scope
# Simple approach: mark line ranges to delete

functions_to_remove = [
    "_sanitize_answer",
    "_sanitize_reasoning", 
    "_safe_flush_point",
    "_filter_reasoning_chunk",
    "_is_tool_call_only",
    "_llm_client",
    "_model",
    "_first_choice",
    "_emit_streamed_answer",
]

# Track which start lines to delete (inclusive) 
# We need to find each function's start and end
# A function ends at: next 'def ' at same indent level, or EOF, or a top-level non-comment/blank line with no indent

delete_ranges = []  # (start_lineno, end_lineno) inclusive-exclusive

for i, line in enumerate(lines):
    stripped = line.lstrip()
    for func in functions_to_remove:
        if stripped.startswith(f"def {func}("):
            # Found start of function
            start = i
            # Find end: next top-level 'def ' or EOF
            end = len(lines)
            for j in range(i + 1, len(lines)):
                ls = lines[j]
                # Check if this line starts a new function at module level
                # (no leading whitespace or just decorator)
                if ls.startswith("def ") and not ls.startswith("async def "):
                    # Check if it's a new function we DON'T want to remove
                    is_target = any(ls.lstrip().startswith(f"def {f}(") for f in functions_to_remove)
                    if not is_target:
                        end = j
                        break
                elif ls.startswith("async def "):
                    is_target = any(ls.lstrip().startswith(f"async def {f}(") for f in functions_to_remove)
                    if not is_target:
                        end = j
                        break
                elif ls.strip() == "" or ls.startswith(" ") or ls.startswith("\t"):
                    continue
                elif ls.startswith("@") or ls.startswith("#"):
                    # Decorators/comments before the next function — continue
                    continue
                else:
                    # Top-level code that's not a function def — this is the end
                    end = j
                    break
            delete_ranges.append((start, end))
            print(f"[OK] Found {func} at lines {start+1}-{end}")
            break

# Sort reverse to avoid index shifting
delete_ranges.sort(reverse=True)

deleted_count = 0
for start, end in delete_ranges:
    # Verify this range actually starts with the expected def
    for func in functions_to_remove:
        if lines[start].lstrip().startswith(f"def {func}(") or lines[start].lstrip().startswith(f"async def {func}("):
            del lines[start:end]
            deleted_count += 1
            break

print(f"[OK] Removed {deleted_count} duplicate function definitions")

# === Step 5: Write result ===
with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(lines)

print(f"\n[DONE] chat_agent.py patched ({len(lines)} lines final)")
print("Run verification: python -c \"from app.services.chat_agent import stream_chat_agent\"")
