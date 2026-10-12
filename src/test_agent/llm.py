from __future__ import annotations

import os
from typing import Any

import httpx


class LLMUnavailable(RuntimeError):
    pass


class OpenAICompatLLM:
    """OpenAI 兼容协议客户端，chat 优先，vision / embedding 复用同一 base_url。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._client = httpx.Client(timeout=timeout)
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    def complete(self, messages: list[dict[str, Any]], *, temperature: float = 0.0) -> str:
        resp = self._client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._model, "messages": messages, "temperature": temperature},
        )
        if resp.status_code != 200:
            raise LLMUnavailable(f"llm http {resp.status_code}: {resp.text[:200]}")
        return resp.json()["choices"][0]["message"]["content"]

    @classmethod
    def from_env(cls) -> "OpenAICompatLLM":
        base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        key = os.getenv("LLM_API_KEY", "")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        if not key:
            raise ValueError("LLM_API_KEY 未配置")
        return cls(base, key, model)


class FakeLLM:
    """离线替身：按脚本返回，用于跑通闭环与单测。"""

    def __init__(self, script: dict[str, str] | None = None) -> None:
        self._script = script or {}
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, Any]], *, temperature: float = 0.0) -> str:
        self.calls.append({"messages": messages, "temperature": temperature})
        last = messages[-1]["content"] if messages else ""
        for trigger, answer in self._script.items():
            if trigger in last:
                return answer
        return "continue"
