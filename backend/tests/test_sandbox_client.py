import httpx
import pytest
from app import sandbox


@pytest.mark.parametrize("error,expected_calls,kind", [
    (httpx.ConnectError("offline"), 3, "executor_error"),
    (httpx.ConnectTimeout("offline"), 3, "executor_timeout"),
    (httpx.ReadTimeout("running"), 1, "executor_timeout"),
])
def test_only_connection_failures_are_safe_to_retry(monkeypatch, error, expected_calls, kind):
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs):
            calls.append(1)
            raise error
    monkeypatch.setattr(sandbox.httpx, "Client", Client)
    monkeypatch.setattr(sandbox.time, "sleep", lambda _: None)
    result = sandbox.run_script("test-id")
    assert result["error_kind"] == kind
    assert len(calls) == expected_calls
