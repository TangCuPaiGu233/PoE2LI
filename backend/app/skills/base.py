"""base.py — Agent Skill 基类。

参照 claw-code 的 Agent 模式：
  - 每个 Skill 是一个 Agent：有状态、有工具、有输出约束
  - 工具通过 `tools` 列表声明，Orchestrator 负责注入
  - 输出为结构化类型，不是裸字符串
"""
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field


class AgentState(Enum):
    IDLE = "idle"
    THINKING = "thinking"       # LLM 分析意图/规划关键词
    RETRIEVING = "retrieving"   # 检索知识库/调用 API
    SYNTHESIZING = "synthesizing"  # LLM 合成回答
    DONE = "done"
    FAILED = "failed"


@dataclass
class AgentResult:
    """Skill 执行的结构化输出。"""
    content: str = ""                    # 给用户看的文本
    reasoning: str = ""                  # 模型思考过程
    sources: list[dict] = field(default_factory=list)  # 参考来源
    trade_data: dict | None = None       # trade_search 专用
    state: AgentState = AgentState.DONE


class BaseSkill(ABC):
    """Agent Skill 基类。

    每个子类是一个独立的 AI 能力单元。
    """

    name: str = "base"
    description: str = ""
    keywords: list[str] = []

    # 该 Skill 需要的工具列表
    tools: list[str] = []

    @abstractmethod
    def matches(self, query: str) -> bool:
        """判断用户意图是否匹配该 Skill。"""

    @abstractmethod
    def system_prompt(self, **kwargs) -> str:
        """返回该 Skill 的系统提示词。"""

    def on_enter(self) -> None:
        """Skill 被激活时调用（状态转换钩子）。"""
        self.state = AgentState.IDLE

    def on_exit(self) -> None:
        """Skill 执行完毕时调用。"""
        self.state = AgentState.DONE
