"""记忆管理模块：长期 RAG 知识库 + 短时上下文压缩。

对齐 docs/DESIGN-v2.md 5.3，记忆做成「外围能力」而非独立 agent：
- MemoryStore 长期记忆，存历史用例 / 缺陷 / 规则 / 元素语义，按语义相似度检索。
- ContextCompressor 短时记忆，上下文超阈值时蒸馏成摘要，模型不可用则离线降级。
- EmbeddingProvider 可插拔：真实场景接 API，离线用特征哈希假 embedding 跑通闭环。

整个模块只依赖标准库，离线可测。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .types import LLM


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...


def _tokenize(text: str) -> list[str]:
    """中文按字 bigram + 单字切分，英文按小写词切分，够离线语义匹配。"""
    tokens: list[str] = []
    tokens.extend(re.findall(r"[a-z0-9_]+", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        tokens.extend(run)
    return tokens


def _hash(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class HashEmbeddingProvider:
    """特征哈希假 embedding：离线、确定、无外部服务，用于离线验证与单测。"""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _tokenize(text):
            h = _hash(token)
            vec[h % self.dim] += 1.0 if (h >> 8) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [v / norm for v in vec]
        return vec


@dataclass
class MemoryItem:
    id: str
    kind: str  # case / defect / rule / element
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)


class MemoryStore:
    """长期 RAG 知识库：按语义相似度检索历史条目，可持久化到 JSON 文件。"""

    def __init__(self, embedder: EmbeddingProvider | None = None) -> None:
        self._embedder = embedder or HashEmbeddingProvider()
        self._items: dict[str, MemoryItem] = {}
        self._order: list[str] = []

    def add(self, kind: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryItem:
        item = MemoryItem(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            content=content,
            metadata=metadata or {},
            embedding=self._embedder.embed(content),
        )
        self._items[item.id] = item
        self._order.append(item.id)
        return item

    def search(self, query: str, kind: str | None = None, top_k: int = 5) -> list[MemoryItem]:
        q = self._embedder.embed(query)
        scored = [
            (_cosine(q, item.embedding), item)
            for item in self._items.values()
            if kind is None or item.kind == kind
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    def all(self, kind: str | None = None) -> list[MemoryItem]:
        return [i for i in self._items.values() if kind is None or i.kind == kind]

    def clear(self) -> None:
        self._items.clear()
        self._order.clear()

    def to_dict(self) -> list[dict[str, Any]]:
        return [
            {"id": i.id, "kind": i.kind, "content": i.content,
             "metadata": i.metadata, "embedding": i.embedding}
            for i in self._items.values()
        ]

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str, embedder: EmbeddingProvider | None = None) -> "MemoryStore":
        store = cls(embedder)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for d in data:
            item = MemoryItem(
                d["id"], d["kind"], d["content"],
                d.get("metadata", {}), d.get("embedding", []),
            )
            if not item.embedding:
                item.embedding = store._embedder.embed(item.content)
            store._items[item.id] = item
            store._order.append(item.id)
        return store


class ContextCompressor:
    """短时上下文压缩：超阈值时蒸馏成摘要，模型不可用则离线降级。"""

    def __init__(self, llm: LLM, max_chars: int = 8000) -> None:
        self._llm = llm
        self._max_chars = max_chars

    def compress(self, entries: list[dict[str, Any]]) -> str:
        text = json.dumps(entries, ensure_ascii=False)
        if len(text) <= self._max_chars:
            return text
        try:
            return self._distill(entries)
        except Exception:
            return self._offline_digest(entries)

    def _distill(self, entries: list[dict[str, Any]]) -> str:
        raw = self._llm.complete(
            [
                {"role": "system", "content": "把以下测试执行历史压缩成简洁摘要，保留关键结论、失败原因与已修复项，去掉重复细节。"},
                {"role": "user", "content": json.dumps(entries, ensure_ascii=False)},
            ]
        )
        return raw.strip()

    @staticmethod
    def _offline_digest(entries: list[dict[str, Any]]) -> str:
        head = "; ".join(
            f"step{e.get('step')}:{e.get('outcome')}" for e in entries[:-3] if "step" in e
        )
        tail = json.dumps(entries[-3:], ensure_ascii=False)
        return f"[压缩 {len(entries)} 条] 前情: {head} | 最近: {tail}"


class Memory:
    """记忆管理门面：一个注入点串起长期知识库与短时压缩，读（检索）写（沉淀）两个方向。"""

    def __init__(
        self,
        store: MemoryStore | None = None,
        compressor: ContextCompressor | None = None,
    ) -> None:
        self.store = store or MemoryStore()
        self.compressor = compressor

    def recall_cases(self, requirement: str, top_k: int = 3) -> list[MemoryItem]:
        return self.store.search(requirement, kind="case", top_k=top_k)

    def recall_defects(self, detail: str, top_k: int = 3) -> list[MemoryItem]:
        return self.store.search(detail, kind="defect", top_k=top_k)

    def remember(self, kind: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryItem:
        return self.store.add(kind, content, metadata)

    def compress(self, entries: list[dict[str, Any]]) -> str:
        if self.compressor is None:
            return json.dumps(entries, ensure_ascii=False)
        return self.compressor.compress(entries)
