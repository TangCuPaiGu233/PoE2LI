"""Site-wide game version defaults and shared user guidance."""

from __future__ import annotations

import re

POE2_SITE_RULE = """## 游戏版本（全站默认）
- 本站专门服务 **Path of Exile 2（流放之路2 / PoE2）**
- 除非用户明确提到「流放1」「PoE1」「Path of Exile 1」，否则一律按 PoE2 理解
- **禁止**追问用户是 PoE1 还是 PoE2；不要提供 PoE1 相关选项或链接
- 引用技能/装备/职业名时，优先使用知识库检索结果中出现的名称。如果检索结果中未出现某个名称，说明该内容不属于当前 PoE2 版本，不要凭空引用
"""


def attach_poe2_rule(prompt: str) -> str:
    return POE2_SITE_RULE + "\n\n" + prompt


_NINJA_HINT = re.compile(r"(?:忍者(?:网)?|poe\.ninja|poe\s*ninja)", re.I)
_COST_HINT = re.compile(
    r"(?:造价|成本|花费|估算|算一下|值多少|多少钱|价格|多少币|花多少|多少e|多少d|市价|bd\s*造价|构建造价)",
    re.I,
)


def is_ninja_cost_guide_query(text: str) -> bool:
    """User wants poe.ninja BD cost estimate but did not paste a build link/code."""
    from app.services.chat_tools import find_build_input

    raw = (text or "").strip()
    if not raw or find_build_input(raw):
        return False
    return bool(_NINJA_HINT.search(raw) and _COST_HINT.search(raw))


NINJA_COST_GUIDE_MARKDOWN = """### 如何估算 poe.ninja BD 造价

本站默认服务 **流放之路2（PoE2）**。要估算某套 BD 的装备市价，请把 **poe.ninja 上的角色链接** 粘贴到对话框：

1. 打开 [poe.ninja PoE2 Builds](https://poe.ninja/poe2/builds)
2. 找到想参考的角色，进入 **角色详情页**
3. 复制浏览器地址栏完整链接（形如 `https://poe.ninja/poe2/builds/联赛名/character/账号/角色名`）
4. 粘贴到本对话框，可附带「算一下这套 BD 造价多少」

我会解析该 BD 的暗金与稀有装备，并逐项查询国服交易行市价后汇总。

**示例发送格式：**
```
https://poe.ninja/poe2/builds/.../character/.../...
算一下这套 BD 造价多少
```
"""
