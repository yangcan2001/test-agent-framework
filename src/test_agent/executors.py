from __future__ import annotations

import time
from typing import Any

import httpx

from .types import CancellationToken, ExecOutcome, ExecResult, SkillKind


class ApiExecutor:
    """API 执行器：超时下沉到 httpx connect / read / write / pool 四级。"""

    kind = SkillKind.API

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def run(self, skill_id: str, params: dict[str, Any], token: CancellationToken) -> ExecResult:
        token.throw_if_cancelled()
        timeout = httpx.Timeout(
            connect=params.get("connect_timeout", 10.0),
            read=params.get("read_timeout", 30.0),
            write=params.get("write_timeout", 10.0),
            pool=params.get("pool_timeout", 5.0),
        )
        if self._client is not None:
            return self._request(self._client, params, timeout, token)
        with httpx.Client(timeout=timeout) as client:
            return self._request(client, params, timeout, token)

    def _request(
        self,
        client: httpx.Client,
        params: dict[str, Any],
        timeout: httpx.Timeout,
        token: CancellationToken,
    ) -> ExecResult:
        start = time.perf_counter()
        try:
            resp = client.request(
                params.get("method", "GET").upper(),
                params["url"],
                headers=params.get("headers"),
                params=params.get("query"),
                json=params.get("json"),
                timeout=timeout,
            )
            token.throw_if_cancelled()
        except httpx.TimeoutException as exc:
            return ExecResult(ExecOutcome.TIMEOUT, str(exc), elapsed=time.perf_counter() - start)
        except Exception as exc:
            return ExecResult(ExecOutcome.ERROR, f"{type(exc).__name__}: {exc}", elapsed=time.perf_counter() - start)

        detail = f"status={resp.status_code}"
        outcome = ExecOutcome.OK
        expect = params.get("expect_status")
        if expect is not None and resp.status_code != expect:
            outcome = ExecOutcome.FAILED
            detail += f" expect={expect}"
        return ExecResult(outcome, detail, resp.text, time.perf_counter() - start)


class UiExecutor:
    """UI 执行器：Playwright 页级超时 + 显式资源释放，消除「假超时」。"""

    kind = SkillKind.UI

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless

    def run(self, skill_id: str, params: dict[str, Any], token: CancellationToken) -> ExecResult:
        token.throw_if_cancelled()
        start = time.perf_counter()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ExecResult(ExecOutcome.ERROR, "playwright not installed", elapsed=time.perf_counter() - start)

        timeout_ms = params.get("timeout_ms", 30_000)
        steps = params.get("steps", [])
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self._headless)
            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                page.goto(params["url"])
                for action in steps:
                    token.throw_if_cancelled()
                    self._apply(page, action)
                token.throw_if_cancelled()
                return ExecResult(ExecOutcome.OK, "ui done", elapsed=time.perf_counter() - start)
            except Exception as exc:
                outcome = ExecOutcome.TIMEOUT if "Timeout" in type(exc).__name__ else ExecOutcome.ERROR
                return ExecResult(outcome, f"{type(exc).__name__}: {exc}", elapsed=time.perf_counter() - start)
            finally:
                browser.close()

    @staticmethod
    def _apply(page, action: dict[str, Any]) -> None:
        op = action["op"]
        if op == "click":
            page.click(action["selector"])
        elif op == "fill":
            page.fill(action["selector"], action["value"])
        elif op == "wait":
            page.wait_for_selector(action["selector"])
        elif op == "assert_text":
            if action["value"] not in page.inner_text(action["selector"]):
                raise AssertionError(f"{action['selector']!r} 文本不符")
        else:
            raise ValueError(f"unknown ui op: {op}")
