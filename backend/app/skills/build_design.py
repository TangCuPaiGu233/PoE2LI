"""build_design.py — BD 设计 Skill。

根据用户提供的职业/升华/核心技能/暗金，深度分析机制并设计可行的 Build 方案。
"""
from app.skills.base import BaseSkill


class BuildDesignSkill(BaseSkill):
    name = "build_design"
    description = "根据职业/升华/核心技能/暗金设计可行的 PoE2 Build 方案"
    keywords = [
        "bd", "build", "构建", "配装", "开荒", "转型", "升级", "加点",
        "天赋怎么点", "技能搭配", "装备搭配", "怎么玩", "设计", "配一套",
        "给我配", "帮我配", "怎么做", "玩法", "builds", "攻略",
    ]

    def matches(self, query: str) -> bool:
        q = query.lower()
        return any(k in q for k in self.keywords)

    def build_prompt(self, context: str, user_msg: str, **kwargs) -> str:
        asc_en = kwargs.get("asc_en", "")
        asc_cn = kwargs.get("asc_cn", "")

        parts = [
            "你是 PoE2 BD 架构师。基于检索到的游戏数据设计可行的 Build 方案。\n\n",
        ]
        if asc_en and asc_cn:
            parts.append(
                "用户关注的升华是 " + str(asc_cn) + "(" + str(asc_en) + ")。"
                "必须先深入分析该升华的核心机制, 再基于机制推导技能和装备选择。\n"
            )
        parts.extend([
            "## 分析步骤\n",
            "1. 读懂核心机制: 仔细阅读升华节点、技能描述中的具体数值和联动关系\n",
            "2. 确定核心技能: 基于机制选出1-2个核心主动技能, 说明为什么它们与机制配合\n",
            "3. 构建辅助链路: 为核心技能搭配辅助宝石, 解释联动逻辑\n",
            "4. 寻找装备支撑: 推荐能强化核心机制的暗金或黄装词缀\n",
            "5. 完善防御: 根据职业特性推荐防御层\n\n",
            "## 输出格式\n",
            "### 核心机制\n",
            "(2-3句话解释核心运作方式, 引用资料中的具体数值)\n\n",
            "### 核心技能\n",
            "- 主动技能 (名称+为什么选它)\n",
            "- 辅助宝石链接 (联动关系)\n\n",
            "### 关键装备\n",
            "- 暗金推荐 (具体名称+作用)\n",
            "- 黄装词缀优先级 (按重要性排序)\n\n",
            "### 防御与天赋\n",
            "- 关键天赋圈\n",
            "- 防御机制\n\n",
            "### 开荒/过渡建议\n",
            "- 哪些装备可以降配\n",
            "- 前期替代技能\n\n",
            "## 规则\n",
            "- 每个推荐必须关联资料中的具体数据, 引用数值\n",
            "- 不编造不存在的装备/技能, 不确定的标注[推测]\n",
            "- 资料不足时诚实说明缺什么信息\n",
            "- 回答末尾列出来源\n\n",
            "资料:\n", context,
        ])
        return "".join(parts)

    def get_chunk_types(self) -> list[str] | None:
        return ["skill", "gem", "passive", "asc_nodes", "item", "mod", "wiki"]
