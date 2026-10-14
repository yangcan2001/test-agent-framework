import json

from test_agent.agent import TestAgent
from test_agent.gates import GateConfig
from test_agent.llm import FakeLLM
from test_agent.memory import Memory
from test_agent.skills import Skill, SkillRegistry
from test_agent.types import ExecOutcome, ExecResult, SkillKind


class StubExecutor:
    kind = SkillKind.PURE

    def __init__(self, fn):
        self._fn = fn

    def run(self, skill_id, params, token):
        return self._fn(skill_id, params)


def main():
    reg = SkillRegistry()
    reg.register(
        Skill(
            "get_order", "查询订单", "GET /api/orders/{id} 校验 200 与返回结构",
            {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
            SkillKind.API, ("api_spec",),
        )
    )
    reg.register(Skill("make_data", "造数", "生成订单测试数据", {"type": "object"}, SkillKind.PURE))

    plan = json.dumps(
        [
            {"skill_id": "make_data", "params": {}, "goal": "生成订单数据"},
            {"skill_id": "get_order", "params": {"id": 1001}, "goal": "校验订单接口返回"},
        ]
    )
    # 离线脚本：规划返回 plan，执行失败时决策 retry
    llm = FakeLLM({"需求": plan, "结果": "retry"})

    state = {"n": 0}

    def runner(skill_id, params):
        if skill_id == "get_order":
            state["n"] += 1
            if state["n"] <= 2:
                return ExecResult(ExecOutcome.FAILED, "AssertionError: expect status 200")
        return ExecResult(ExecOutcome.OK, "status=200")

    executors = {SkillKind.PURE: StubExecutor(runner), SkillKind.API: StubExecutor(runner)}

    # 记忆层：预置一条历史用例，规划时会召回；任务结束自动沉淀 case/defect
    mem = Memory()
    mem.remember("case", "订单接口 GET /orders/{id} 校验 200 与返回结构")

    agent = TestAgent(llm, reg, executors, GateConfig(step_retry_budget=2), memory=mem)

    result = agent.run("对订单接口做一次冒烟测试", "openapi")

    print("status:", result.status)
    for s in result.steps:
        print(f"  step {s.step.index} {s.step.skill_id}: {s.status} (attempts={s.attempts})")
    print("trace entries:", len(result.trace.dump()))
    print("memory items:", [(i.kind, i.content) for i in mem.store.all()])


if __name__ == "__main__":
    main()
