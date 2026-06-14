"""build_design.py — BD 设计 Skill。工具: rag_search / entity_resolve。"""
from app.core.game_context import attach_poe2_rule
from app.skills.base import BaseSkill


class BuildDesignSkill(BaseSkill):
    name = "build_design"
    description = "根据职业/升华/核心技能设计可行的 PoE2 Build 方案"
    tools = ["rag_search", "entity_resolve", "keyword_correct", "structured_lookup"]
    keywords = [
        "bd", "build", "构建", "配装", "开荒", "转型", "升级", "加点",
        "天赋怎么点", "技能搭配", "装备搭配", "怎么玩", "设计", "配一套",
        "给我配", "帮我配", "怎么做", "玩法", "builds", "攻略",
    ]

    def matches(self, query: str) -> bool:
        q = query.lower()
        return any(k in q for k in self.keywords)

    def system_prompt(self, **kwargs) -> str:
        asc_en = kwargs.get("asc_en", "")
        asc_cn = kwargs.get("asc_cn", "")
        context = kwargs.get("context", "")

        parts = [
            "你是 PoE2 BD 架构师。基于检索数据设计可行的 Build 方案。\n\n",
        ]
        if asc_en and asc_cn:
            parts.append(
                "用户关注的升华: " + str(asc_cn) + "(" + str(asc_en) + ")。"
                "先深入分析该升华的核心机制, 再推导技能和装备选择。\n"
            )
        parts.extend([
            "## 分析步骤\n",
            "1. 读懂核心机制: 阅读升华节点、技能描述中的数值和联动关系\n",
            "2. 确定核心技能: 基于机制选1-2个核心主动技能, 说明配合原因\n",
            "3. 构建辅助链路: 为核心技能搭配辅助宝石\n",
            "4. 寻找装备支撑: 推荐暗金或黄装词缀\n",
            "5. 完善防御: 根据职业推荐防御层\n\n",
            "## 输出格式\n",
            "### 核心机制\n",
            "(2-3句话, 引用具体数值)\n\n",
            "### 核心技能\n",
            "- 主动技能 + 为什么选它\n",
            "- 辅助宝石链接\n\n",
            "### 关键装备\n",
            "- 暗金推荐 (名称+作用)\n",
            "- 黄装词缀优先级\n\n",
            "### 防御与天赋\n",
            "- 关键天赋圈\n",
            "- 防御机制\n\n",
            "### 过渡建议\n",
            "- 降配选项\n",
            "- 替代技能\n\n",
            "## 规则\n",
            "- 每个推荐关联资料中的具体数据\n",
            "- 用 ### 做小节标题, **粗体** 标关键数值\n",
            "- 不确定的标注[推测]\n",
            "- 资料不足诚实说明\n\n",
            "资料:\n", context,
        ])
        return attach_poe2_rule("".join(parts))
