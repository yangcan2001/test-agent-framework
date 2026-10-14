import json

from test_agent.agent import TestAgent
from test_agent.llm import FakeLLM
from test_agent.memory import ContextCompressor, HashEmbeddingProvider, Memory, MemoryStore
from test_agent.skills import Skill, SkillRegistry
from test_agent.types import ExecOutcome, ExecResult, SkillKind


class _Boom:
    def complete(self, messages, *, temperature=0.0):
        raise RuntimeError("llm down")


class _StubExecutor:
    kind = SkillKind.PURE

    def run(self, skill_id, params, token):
        return ExecResult(ExecOutcome.OK, "done")


def test_hash_embedding_deterministic_and_normalized():
    e = HashEmbeddingProvider()
    a, b = e.embed("订单接口"), e.embed("订单接口")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


def test_store_search_returns_similar():
    store = MemoryStore()
    store.add("case", "订单接口 GET /orders/{id} 校验 200")
    store.add("case", "用户登录 POST /login 校验 token")
    hits = store.search("查询订单接口", kind="case", top_k=1)
    assert hits and "订单" in hits[0].content


def test_store_search_filters_by_kind():
    store = MemoryStore()
    store.add("case", "订单接口用例")
    store.add("defect", "订单接口断言失败")
    assert all(h.kind == "defect" for h in store.search("订单接口", kind="defect"))


def test_store_persistence_roundtrip(tmp_path):
    store = MemoryStore()
    store.add("defect", "登录超时连接拒绝", {"skill": "login"})
    path = tmp_path / "mem.json"
    store.save(str(path))
    loaded = MemoryStore.load(str(path), HashEmbeddingProvider())
    assert len(loaded.all()) == 1
    assert loaded.all()[0].content == "登录超时连接拒绝"
    assert loaded.search("登录超时")[0].kind == "defect"


def test_compressor_passthrough_under_threshold():
    c = ContextCompressor(FakeLLM(), max_chars=100000)
    entries = [{"step": 0, "outcome": "ok"}]
    assert c.compress(entries) == json.dumps(entries, ensure_ascii=False)


def test_compressor_offline_digest_over_threshold():
    c = ContextCompressor(_Boom(), max_chars=1)
    entries = [{"step": i, "outcome": "ok"} for i in range(5)]
    assert "压缩 5 条" in c.compress(entries)


def test_memory_facade_recall_and_remember():
    m = Memory()
    m.remember("case", "订单接口冒烟通过")
    m.remember("defect", "订单接口断言失败 expect 200")
    assert m.recall_cases("对订单接口做冒烟")[0].kind == "case"
    assert m.recall_defects("订单接口断言失败")[0].kind == "defect"


def test_agent_writeback_records_case():
    reg = SkillRegistry()
    reg.register(Skill("gen_data", "造数", "纯逻辑造数", {"type": "object"}, SkillKind.PURE))
    plan = json.dumps([{"skill_id": "gen_data", "params": {}, "goal": "生成订单数据"}])
    llm = FakeLLM({"需求": plan})

    mem = Memory()
    agent = TestAgent(llm, reg, {SkillKind.PURE: _StubExecutor()}, memory=mem)
    agent.run("对订单接口做冒烟", "text")

    assert len(mem.store.all("case")) == 1
    assert mem.recall_cases("对订单接口做冒烟")[0].kind == "case"


def test_agent_writeback_records_defect():
    reg = SkillRegistry()
    reg.register(Skill("gen_data", "造数", "纯逻辑造数", {"type": "object"}, SkillKind.PURE))
    plan = json.dumps([{"skill_id": "gen_data", "params": {}, "goal": "生成订单数据"}])
    llm = FakeLLM({"需求": plan, "结果": "continue"})

    class _Fail:
        kind = SkillKind.PURE

        def run(self, skill_id, params, token):
            return ExecResult(ExecOutcome.FAILED, "AssertionError: expect 200")

    mem = Memory()
    agent = TestAgent(llm, reg, {SkillKind.PURE: _Fail()}, memory=mem)
    result = agent.run("对订单接口做冒烟", "text")

    assert result.steps[0].status == "failed"
    assert len(mem.store.all("defect")) == 1
    assert mem.recall_defects("expect 200 断言失败")[0].kind == "defect"
