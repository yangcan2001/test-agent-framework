from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from .types import SkillKind


class SkillValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    params_schema: dict[str, Any]
    kind: SkillKind = SkillKind.PURE
    requires: tuple[str, ...] = ()

    def validate(self, params: dict[str, Any]) -> None:
        """参数经 JSON Schema 在执行前拦截。"""
        validator = Draft202012Validator(self.params_schema)
        errors = sorted(validator.iter_errors(params), key=lambda e: list(e.absolute_path))
        if errors:
            raise SkillValidationError(f"skill {self.id!r}: {errors[0].message}")


class SkillRegistry:
    """声明式技能注册表：id / name / description / params_schema / kind / requires。"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if skill.id in self._skills:
            raise ValueError(f"duplicate skill id: {skill.id}")
        self._skills[skill.id] = skill

    def get(self, skill_id: str) -> Skill:
        if skill_id not in self._skills:
            raise KeyError(f"unknown skill: {skill_id}")
        return self._skills[skill_id]

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def allowed(self, capabilities: set[str]) -> list[Skill]:
        """能力掩码过滤：仅返回执行条件满足的技能。"""
        return [s for s in self._skills.values() if set(s.requires) <= capabilities]

    def render_for_prompt(self, capabilities: set[str]) -> str:
        """技能描述动态渲染进规划 prompt，新增技能无需改 prompt。"""
        lines = [f"- {s.id}: {s.description}" for s in self.allowed(capabilities)]
        return "\n".join(lines) if lines else "(无可用技能)"
