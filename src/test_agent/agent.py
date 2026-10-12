from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gates import GateConfig, StepBudget, TaskGate
from .planner import Planner
from .react import ReActRunner
from .reflection import Reflector
from .skills import SkillRegistry
from .trace import Trace
from .types import CancellationToken, Executor, LLM, SkillKind

# 文档类型 → 可用执行能力；能力掩码据此禁用不具备执行条件的技能
_DOC_CAPABILITIES = {
    "openapi": {"api_spec"},
    "swagger": {"api_spec"},
    "ui": {"browser"},
    "text": set(),
}


@dataclass
class AgentResult:
    requirement: str
    status: str
    steps: list[Any] = field(default_factory=list)
    trace: Trace = field(default_factory=Trace)


class TestAgent:
    """自主测试 Agent 顶层编排：规划 → 逐步骤 ReAct 微循环 → 汇总。"""

    def __init__(
        self,
        llm: LLM,
        registry: SkillRegistry,
        executors: dict[SkillKind, Executor],
        config: GateConfig | None = None,
    ) -> None:
        self._config = config or GateConfig()
        self._planner = Planner(llm, registry)
        self._react = ReActRunner(registry, executors, llm, Reflector(llm))

    def run(self, requirement: str, document_kind: str = "text") -> AgentResult:
        capabilities = _DOC_CAPABILITIES.get(document_kind, set())
        plan = self._planner.plan(requirement, capabilities)
        gate = TaskGate(self._config)
        token = CancellationToken()
        trace = Trace()
        result = AgentResult(requirement=requirement, status="completed", trace=trace)

        for step in plan.steps:
            budget = StepBudget.from_config(self._config)
            step_result = self._react.run_step(step, budget, token, gate, trace)
            result.steps.append(step_result)
            if step_result.status == "aborted":
                result.status = "aborted"
                break

        return result
