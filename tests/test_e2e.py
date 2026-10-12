import json

from test_agent.agent import TestAgent
from test_agent.gates import GateConfig
from test_agent.llm import FakeLLM
from test_agent.skills import Skill, SkillRegistry
from test_agent.types import ExecOutcome, ExecResult, SkillKind


class StubExecutor:
    kind = SkillKind.PURE

    def __init__(self, fn, kind: SkillKind = SkillKind.PURE):
        self._fn = fn
        self.kind = kind

    def run(self, skill_id, params, token):
        return self._fn(skill_id, params)


def _registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(Skill("get_order", "查订单", "GET /orders/{id}", {"type": "object"}, SkillKind.API, ("api_spec",)))
    reg.register(Skill("gen_data", "造数", "纯逻辑造数", {"type": "object"}, SkillKind.PURE))
    return reg


def _executors(fn) -> dict:
    return {SkillKind.PURE: StubExecutor(fn), SkillKind.API: StubExecutor(fn, SkillKind.API)}


def test_e2e_all_ok():
    plan = json.dumps([{"skill_id": "gen_data", "params": {}, "goal": "造数"}])
    llm = FakeLLM({"需求": plan})
    result = TestAgent(llm, _registry(), _executors(lambda *_: ExecResult(ExecOutcome.OK, "done"))).run(
        "对订单做一次冒烟", "text"
    )
    assert result.status == "completed"
    assert result.steps[0].status == "ok"


def test_e2e_retry_then_ok():
    plan = json.dumps([{"skill_id": "gen_data", "params": {}, "goal": "造数"}])
    llm = FakeLLM({"需求": plan, "结果": "retry"})
    state = {"n": 0}

    def flaky(skill_id, params):
        state["n"] += 1
        if state["n"] == 1:
            return ExecResult(ExecOutcome.FAILED, "AssertionError: expect status 200")
        return ExecResult(ExecOutcome.OK, "done")

    result = TestAgent(llm, _registry(), _executors(flaky), GateConfig(step_retry_budget=2)).run(
        "对订单做一次冒烟", "text"
    )
    assert result.steps[0].status == "ok"
    assert state["n"] == 2


def test_e2e_fix_then_ok():
    plan = json.dumps([{"skill_id": "gen_data", "params": {}, "goal": "造数"}])
    llm = FakeLLM({"需求": plan, "结果": "fix", "失败": json.dumps({"id": 1})})
    state = {"n": 0}

    def flaky(skill_id, params):
        state["n"] += 1
        if state["n"] == 1:
            return ExecResult(ExecOutcome.FAILED, "AssertionError: expect status 200")
        return ExecResult(ExecOutcome.OK, "done")

    result = TestAgent(llm, _registry(), _executors(flaky)).run("对订单做一次冒烟", "text")
    assert result.steps[0].status == "ok"
    assert state["n"] == 2


def test_e2e_abort_propagates():
    plan = json.dumps([{"skill_id": "gen_data", "params": {}, "goal": "造数"}])
    llm = FakeLLM({"需求": plan, "结果": "abort"})
    result = TestAgent(
        llm, _registry(), _executors(lambda *_: ExecResult(ExecOutcome.FAILED, "boom"))
    ).run("对订单做一次冒烟", "text")
    assert result.status == "aborted"
    assert result.steps[0].status == "aborted"
