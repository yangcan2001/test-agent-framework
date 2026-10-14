from __future__ import annotations

from .memory import Memory
from .types import Action, ExecOutcome, ExecResult, LLM

_DECIDE_SYSTEM = "你是测试执行决策器。只返回一个词：continue / retry / fix / abort。"
_DEFAULT_RULES = {
    "timeout": Action.RETRY,
    "timed out": Action.RETRY,
    "connection": Action.RETRY,
    "refused": Action.RETRY,
    "assert": Action.FIX,
    "mismatch": Action.FIX,
    "expect": Action.FIX,
    "not found": Action.FIX,
    "keyerror": Action.FIX,
    "jsondecodeerror": Action.FIX,
}


class Reflector:
    """反思三级降级：模型 → 关键词规则 → 默认决策，保证模型不可用时任务不中断。"""

    def __init__(
        self,
        llm: LLM,
        rules: dict[str, Action] | None = None,
        memory: Memory | None = None,
    ) -> None:
        self._llm = llm
        self._rules = rules or _DEFAULT_RULES
        self._memory = memory

    def decide(self, step_goal: str, result: ExecResult) -> Action:
        try:
            return self._model_decide(step_goal, result)
        except Exception:
            return self._rule_decide(result)

    def _model_decide(self, step_goal: str, result: ExecResult) -> Action:
        user = f"步骤目标：{step_goal}\n执行结果：{result.outcome.value} {result.detail}"
        if self._memory is not None:
            defects = self._memory.recall_defects(f"{step_goal} {result.detail}")
            if defects:
                lines = "\n".join(f"- {d.content}" for d in defects)
                user += f"\n相似历史缺陷（参考）：\n{lines}"
        raw = self._llm.complete(
            [
                {"role": "system", "content": _DECIDE_SYSTEM},
                {"role": "user", "content": user},
            ]
        )
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> Action:
        text = raw.strip().lower()
        for action in Action:
            if action.value in text:
                return action
        return Action.CONTINUE

    def _rule_decide(self, result: ExecResult) -> Action:
        if result.outcome == ExecOutcome.TIMEOUT:
            return Action.RETRY
        lowered = result.detail.lower()
        for keyword, action in self._rules.items():
            if keyword in lowered:
                return action
        return Action.CONTINUE
