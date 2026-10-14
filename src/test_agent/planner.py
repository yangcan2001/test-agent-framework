from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .memory import Memory
from .skills import SkillRegistry
from .types import LLM


@dataclass
class Step:
    index: int
    skill_id: str
    params: dict[str, Any]
    goal: str = ""


@dataclass
class Plan:
    steps: list[Step]


class Planner:
    """外层 Plan-and-Solve：一次性任务分解 + 策略生成。"""

    def __init__(self, llm: LLM, registry: SkillRegistry, memory: Memory | None = None) -> None:
        self._llm = llm
        self._registry = registry
        self._memory = memory

    def plan(self, requirement: str, capabilities: set[str]) -> Plan:
        skills_block = self._registry.render_for_prompt(capabilities)
        prompt = (
            "你是测试策略规划器，把需求一次性拆成测试步骤。\n"
            f"可用技能（只能从中选择，禁止臆造）：\n{skills_block}\n"
            f"{self._recall_cases(requirement)}"
            '输出 JSON 数组，每项形如 {"skill_id": "...", "params": {...}, "goal": "..."}。\n'
            f"需求文档：\n{requirement}"
        )
        raw = self._llm.complete([{"role": "user", "content": prompt}])
        return self._parse(raw)

    def _recall_cases(self, requirement: str) -> str:
        """规划时检索相关历史用例作为参考注入 prompt；无记忆层时返回空串。"""
        if self._memory is None:
            return ""
        cases = self._memory.recall_cases(requirement)
        if not cases:
            return ""
        lines = "\n".join(f"- {c.content}" for c in cases)
        return f"相关历史用例（仅供参考，不要照抄）：\n{lines}\n"

    @staticmethod
    def _parse(raw: str) -> Plan:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[-1]
        data = json.loads(text)
        steps = [
            Step(i, item["skill_id"], item.get("params", {}), item.get("goal", ""))
            for i, item in enumerate(data)
        ]
        return Plan(steps)
