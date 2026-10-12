import httpx
import pytest

from test_agent.executors import ApiExecutor
from test_agent.types import Cancelled, CancellationToken, ExecOutcome


def test_api_timeout_classified():
    def handler(request):
        raise httpx.ReadTimeout("read timed out")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = ApiExecutor(client).run("x", {"url": "http://x", "method": "GET"}, CancellationToken())
    assert result.outcome == ExecOutcome.TIMEOUT


def test_api_ok_and_expect_mismatch():
    def handler(request):
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    executor = ApiExecutor(client)
    token = CancellationToken()
    assert executor.run("x", {"url": "http://x", "expect_status": 200}, token).outcome == ExecOutcome.OK
    assert executor.run("x", {"url": "http://x", "expect_status": 201}, token).outcome == ExecOutcome.FAILED


def test_cancellation_raises_before_execution():
    token = CancellationToken()
    token.cancel()
    with pytest.raises(Cancelled):
        ApiExecutor().run("x", {"url": "http://x"}, token)
