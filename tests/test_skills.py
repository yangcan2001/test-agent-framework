import pytest

from test_agent.skills import Skill, SkillRegistry, SkillValidationError
from test_agent.types import SkillKind


def _api_skill() -> Skill:
    return Skill(
        id="get_user",
        name="查询用户",
        description="GET /users/{id} 校验返回",
        params_schema={
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
            "additionalProperties": False,
        },
        kind=SkillKind.API,
        requires=("api_spec",),
    )


def test_validate_ok():
    _api_skill().validate({"id": 1})


def test_validate_rejects_missing_and_wrong_type():
    with pytest.raises(SkillValidationError):
        _api_skill().validate({})
    with pytest.raises(SkillValidationError):
        _api_skill().validate({"id": "x"})


def test_registry_duplicate_and_lookup():
    reg = SkillRegistry()
    reg.register(_api_skill())
    with pytest.raises(ValueError):
        reg.register(_api_skill())
    with pytest.raises(KeyError):
        reg.get("nope")


def test_capability_mask_filters_skills():
    reg = SkillRegistry()
    reg.register(_api_skill())
    reg.register(Skill("gen_data", "造数", "纯逻辑造数", {"type": "object"}, SkillKind.PURE))
    assert [s.id for s in reg.allowed({"api_spec"})] == ["get_user", "gen_data"]
    assert [s.id for s in reg.allowed(set())] == ["gen_data"]


def test_render_for_prompt_only_lists_allowed():
    reg = SkillRegistry()
    reg.register(_api_skill())
    text = reg.render_for_prompt(set())
    assert "get_user" not in text
    assert "(无可用技能)" in text
