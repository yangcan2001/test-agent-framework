from __future__ import annotations

from typing import Any


class Trace:
    """决策与执行结果全量落盘，供复盘。"""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, **entry: Any) -> None:
        self.entries.append(entry)

    def dump(self) -> list[dict[str, Any]]:
        return list(self.entries)
