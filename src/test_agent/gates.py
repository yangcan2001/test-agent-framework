from __future__ import annotations

from dataclasses import dataclass


class GateExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class GateConfig:
    task_max_steps: int = 50
    task_max_tokens: int = 200_000
    step_retry_budget: int = 2
    step_fix_budget: int = 1


@dataclass
class TaskGate:
    """任务级闸门：全局迭代与 token 上限，对应「烧钱」。"""

    config: GateConfig
    steps_used: int = 0
    tokens_used: int = 0

    def consume_step(self) -> None:
        self.steps_used += 1
        if self.steps_used > self.config.task_max_steps:
            raise GateExceeded(f"task step budget exceeded ({self.config.task_max_steps})")

    def consume_tokens(self, n: int) -> None:
        self.tokens_used += n
        if self.tokens_used > self.config.task_max_tokens:
            raise GateExceeded(f"task token budget exceeded ({self.config.task_max_tokens})")


@dataclass
class StepBudget:
    """步骤级闸门：retry / fix 预算，对应「死循环」。"""

    retry_left: int
    fix_left: int

    @classmethod
    def from_config(cls, config: GateConfig) -> "StepBudget":
        return cls(config.step_retry_budget, config.step_fix_budget)
