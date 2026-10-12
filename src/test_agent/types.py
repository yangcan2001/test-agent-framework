from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Action(StrEnum):
    CONTINUE = "continue"
    RETRY = "retry"
    FIX = "fix"
    ABORT = "abort"


class SkillKind(StrEnum):
    PURE = "pure"  # 纯逻辑能力，不进反思循环
    API = "api"
    UI = "ui"


class ExecOutcome(StrEnum):
    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class ExecResult:
    outcome: ExecOutcome
    detail: str = ""
    data: Any = None
    elapsed: float = 0.0


class Cancelled(Exception):
    """任务被取消。"""


class CancellationToken:
    """贯穿全链路的取消令牌，配合执行器原生超时消除「外包线程池假超时」。"""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def throw_if_cancelled(self) -> None:
        if self._cancelled:
            raise Cancelled("task cancelled")


@runtime_checkable
class LLM(Protocol):
    def complete(self, messages: list[dict[str, Any]], *, temperature: float = 0.0) -> str: ...


@runtime_checkable
class Executor(Protocol):
    kind: SkillKind

    def run(self, skill_id: str, params: dict[str, Any], token: CancellationToken) -> ExecResult: ...
