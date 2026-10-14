from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI
from pydantic import BaseModel

from .agent import TestAgent
from .executors import ApiExecutor, UiExecutor
from .llm import OpenAICompatLLM
from .memory import Memory
from .skills import SkillRegistry
from .types import SkillKind


class RunRequest(BaseModel):
    requirement: str
    document_kind: str = "text"


@lru_cache
def build_agent() -> TestAgent:
    # 实际使用时在这里注册业务技能，示例见 examples/demo.py
    registry = SkillRegistry()
    executors = {SkillKind.API: ApiExecutor(), SkillKind.UI: UiExecutor()}
    # 记忆默认走内存 + 特征哈希降级；要跨进程持久化，改用 MemoryStore.save/load 落 JSON
    return TestAgent(OpenAICompatLLM.from_env(), registry, executors, memory=Memory())


app = FastAPI(title="test-agent")


@app.post("/run")
def run(req: RunRequest) -> dict:
    result = build_agent().run(req.requirement, req.document_kind)
    return {
        "status": result.status,
        "steps": [
            {"index": s.step.index, "skill": s.step.skill_id, "status": s.status, "attempts": s.attempts}
            for s in result.steps
        ],
        "trace": result.trace.dump(),
    }
