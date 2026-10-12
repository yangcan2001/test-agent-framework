from __future__ import annotations

import json
from dataclasses import dataclass

from .gates import StepBudget, TaskGate
from .planner import Step
from .reflection import Reflector
from .skills import SkillRegistry
from .trace import Trace
from .types import Action, CancellationToken, ExecOutcome, ExecResult, Executor, LLM, SkillKind


@dataclass
class StepResult:
    step: Step
    status: str  # ok / failed / aborted
    attempts: int
    final: ExecResult


class DecisionRemapper:
    """预算感知的决策重映射：retry 耗尽降级 fix，fix 耗尽降级 continue。"""

    @staticmethod
    def remap(decision: Action, budget: StepBudget) -> Action:
        if decision == Action.RETRY and budget.retry_left <= 0:
            return Action.FIX if budget.fix_left > 0 else Action.CONTINUE
        if decision == Action.FIX and budget.fix_left <= 0:
            return Action.CONTINUE
        return decision


class ReActRunner:
    """内层 ReAct 微循环：对每个步骤运行 EXECUTE → REFLECT → DECIDE。"""

    def __init__(
        self,
        registry: SkillRegistry,
        executors: dict[SkillKind, Executor],
        llm: LLM,
        reflector: Reflector,
    ) -> None:
        self._registry = registry
        self._executors = executors
        self._llm = llm
        self._reflector = reflector

    def run_step(
        self,
        step: Step,
        budget: StepBudget,
        token: CancellationToken,
        gate: TaskGate,
        trace: Trace,
    ) -> StepResult:
        attempts = 0
        while True:
            token.throw_if_cancelled()
            gate.consume_step()
            attempts += 1

            skill = self._registry.get(step.skill_id)
            skill.validate(step.params)
            executor = self._executors[skill.kind]
            result = executor.run(step.skill_id, step.params, token)
            trace.record(
                step=step.index, skill=step.skill_id, attempt=attempts,
                outcome=result.outcome.value, detail=result.detail,
            )

            if result.outcome == ExecOutcome.OK:
                trace.record(step=step.index, decision=Action.CONTINUE.value, reason="ok")
                return StepResult(step, "ok", attempts, result)

            decision = self._reflector.decide(step.goal, result)
            decision = DecisionRemapper.remap(decision, budget)
            trace.record(step=step.index, attempt=attempts, decision=decision.value)

            if decision == Action.CONTINUE:
                return StepResult(step, "failed", attempts, result)
            if decision == Action.RETRY:
                budget.retry_left -= 1
                continue
            if decision == Action.FIX:
                budget.fix_left -= 1
                step = self._repair(step, result)
                continue
            if decision == Action.ABORT:
                return StepResult(step, "aborted", attempts, result)
            return StepResult(step, "failed", attempts, result)

    def _repair(self, step: Step, result: ExecResult) -> Step:
        raw = self._llm.complete(
            [
                {"role": "system", "content": "修复测试步骤参数。只输出修正后的 params JSON 对象。"},
                {"role": "user", "content": f"技能 {step.skill_id} 执行失败：{result.detail}\n原参数：{step.params}"},
            ]
        )
        params = json.loads(raw.strip())
        return Step(step.index, step.skill_id, params, step.goal)
