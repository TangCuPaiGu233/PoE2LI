"""Generate suggested follow-up questions after a chat answer."""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

from app.core.game_context import POE2_SITE_RULE

FOLLOW_UP_SYSTEM = POE2_SITE_RULE + "\n\n" + """你是 PoE2 对话助手。根据用户刚才的问题和助手已给出的回答，生成 3 条用户最可能继续追问的中文短句。

要求：
- 每条是完整、可单独发送的用户问题（15~45 字为宜）
- 与当前话题紧密相关，有递进性（深入机制 / 装备实践 / 对比扩展）
- 不要重复用户原问题或回答中已完整覆盖的内容
- 不要编造具体数值或物品名（除非回答里已出现）
- 只输出 JSON：{"questions": ["...", "...", "..."]}
"""


def _normalize_questions(raw: list | None, *, limit: int = 3) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        q = re.sub(r"\s+", " ", str(item or "").strip())
        if len(q) < 4 or q in seen:
            continue
        seen.add(q)
        out.append(q[:120])
        if len(out) >= limit:
            break
    return out


async def generate_follow_up_questions(
    user_msg: str,
    assistant_answer: str,
    *,
    limit: int = 3,
) -> list[str]:
    answer = (assistant_answer or "").strip()
    question = (user_msg or "").strip()
    if not answer or not question:
        return []

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1"),
        api_key=os.getenv("LLM_API_KEY", ""),
    )
    model = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
    trimmed_answer = answer[:3500] if len(answer) > 3500 else answer

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": FOLLOW_UP_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"用户问题：{question[:800]}\n\n"
                        f"助手回答（节选）：\n{trimmed_answer}\n\n"
                        "请生成 3 条追问。"
                    ),
                },
            ],
            temperature=0.4,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        data = json.loads(raw)
        return _normalize_questions(data.get("questions"), limit=limit)
    except Exception as e:
        logger.warning("follow_up generation failed: %s", e)
        return []
