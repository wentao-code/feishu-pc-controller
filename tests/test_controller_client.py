import json
from urllib.error import HTTPError

import pytest

from command_registry import CommandRegistry
from controller_client import ControlClient, ControlClientError


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        return None


def test_start_sends_bearer_token_and_target_action():
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(
            {
                "request_id": "req-1",
                "accepted": True,
                "status": "accepted",
                "task_id": "task-1",
            }
        )

    target = CommandRegistry().resolve("抖音：开始运行")
    client = ControlClient("http://127.0.0.1:8761", "secret", timeout=2, opener=opener)

    response = client.start(target, "req-1")

    request, timeout = calls[0]
    assert request.get_header("Authorization") == "Bearer secret"
    assert json.loads(request.data) == {"request_id": "req-1", "action": "start"}
    assert timeout == 2
    assert response.task_id == "task-1"


def test_stop_sends_stop_action():
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(
            {
                "request_id": "stop-1",
                "accepted": True,
                "status": "accepted",
                "message": "已提交停止请求",
                "task_id": "run-1",
            }
        )

    target = CommandRegistry().resolve("抖音：停止下载")
    client = ControlClient("http://127.0.0.1:8762", "secret", opener=opener)

    response = client.stop(target, "stop-1")

    request, _timeout = calls[0]
    assert json.loads(request.data) == {"request_id": "stop-1", "action": "stop"}
    assert response.message == "已提交停止请求"
    assert response.task_id == "run-1"


def test_shutdown_sends_distinct_application_shutdown_action():
    calls = []

    def opener(request, timeout):
        calls.append(request)
        return FakeResponse(
            {
                "request_id": "close-1",
                "accepted": True,
                "status": "accepted",
                "message": "关闭请求已接受",
            }
        )

    target = CommandRegistry().resolve("104")
    client = ControlClient("http://127.0.0.1:8761", "secret", opener=opener)

    response = client.shutdown(target, "close-1")

    assert json.loads(calls[0].data) == {"request_id": "close-1", "action": "shutdown"}
    assert response.accepted is True
    assert response.message == "关闭请求已接受"


def test_get_status_returns_json_payload():
    def opener(_request, timeout):
        assert timeout == 5.0
        return FakeResponse({"gui_running": True, "busy": False})

    target = CommandRegistry().resolve("抖音：开始下载")
    client = ControlClient("http://127.0.0.1:8762/", "secret", opener=opener)

    assert client.get_status(target) == {"gui_running": True, "busy": False}


def test_http_error_is_mapped_to_control_client_error():
    def opener(request, timeout):
        assert timeout == 5.0
        body = json.dumps({"reason": "当前配置未锁定"}).encode("utf-8")
        raise HTTPError(request.full_url, 409, "Conflict", {}, FakeResponse(body))

    target = CommandRegistry().resolve("抖音：开始运行")
    client = ControlClient("http://127.0.0.1:8761", "secret", opener=opener)

    with pytest.raises(ControlClientError, match="当前配置未锁定"):
        client.start(target, "req-1")
