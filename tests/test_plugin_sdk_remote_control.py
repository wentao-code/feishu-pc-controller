import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from feishu_plugin_sdk.remote_control import RemoteControlServer, StatusSnapshot


@pytest.fixture
def server():
    snapshot = StatusSnapshot(gui_running=True, ready=True, busy=False)
    calls = []
    control = RemoteControlServer(
        snapshot.get,
        lambda action, request_id: calls.append((action, request_id))
        or {"accepted": True, "status": "accepted", "task_id": request_id},
        token="secret",
        port=0,
        manifest_provider=lambda: {
            "schema_version": "1.0",
            "plugin_id": "test_plugin",
            "label": "测试插件",
            "version": "1.0.0",
            "protocol": {
                "manifest": "/api/v1/manifest",
                "status": "/api/v1/status",
                "commands": "/api/v1/commands",
            },
            "actions": [{"name": "start", "label": "开始", "aliases": ["test start"]}],
        },
        required_ready_fields=("gui_running", "ready"),
        required_status_values={"mode": ("douyin",)},
        command_timeout=0.1,
    )
    control.start_in_thread()
    try:
        yield control, snapshot, calls
    finally:
        control.stop()


def _request(server, path, *, method="GET", payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    return Request(
        server.base_url + path,
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
        },
    )


def test_sdk_exposes_status_and_requires_bearer_token(server):
    control, snapshot, _calls = server
    snapshot.update(mode="douyin")

    with urlopen(_request(control, "/api/v1/status"), timeout=2) as response:
        payload = json.loads(response.read())
    assert payload["mode"] == "douyin"

    with pytest.raises(HTTPError) as error:
        urlopen(
            Request(control.base_url + "/api/v1/status", method="GET"),
            timeout=2,
        )
    assert error.value.code == 401


def test_sdk_exposes_manifest_with_the_same_authentication_contract(server):
    control, _snapshot, _calls = server

    with urlopen(_request(control, "/api/v1/manifest"), timeout=2) as response:
        payload = json.loads(response.read())

    assert payload["plugin_id"] == "test_plugin"
    assert payload["protocol"]["commands"] == "/api/v1/commands"

    with pytest.raises(HTTPError) as error:
        urlopen(Request(control.base_url + "/api/v1/manifest", method="GET"), timeout=2)
    assert error.value.code == 401


def test_sdk_does_not_execute_command_after_gui_response_timeout(server):
    control, snapshot, calls = server
    snapshot.update(mode="douyin")

    with pytest.raises(HTTPError) as error:
        urlopen(
            _request(
                control,
                "/api/v1/commands",
                method="POST",
                payload={"request_id": "expired-1", "action": "start"},
            ),
            timeout=2,
        )
    assert error.value.code == 504

    assert control.drain() == 0
    assert calls == []


def test_sdk_stop_requires_busy_task_and_runs_on_draining_thread(server):
    control, snapshot, calls = server
    snapshot.update(mode="douyin", busy=True)
    drain_thread_id = threading.get_ident()
    callback_threads = []
    control.command_handler = lambda action, request_id: callback_threads.append(
        (action, request_id, threading.get_ident())
    ) or {"accepted": True, "status": "accepted"}

    request = _request(
        control,
        "/api/v1/commands",
        method="POST",
        payload={"request_id": "stop-1", "action": "stop"},
    )
    result = []
    thread = threading.Thread(
        target=lambda: result.append(json.loads(urlopen(request, timeout=2).read()))
    )
    thread.start()
    assert control.wait_for_command(1)
    assert control.drain() == 1
    thread.join(timeout=2)

    assert result == [{"accepted": True, "status": "accepted"}]
    assert calls == []
    assert callback_threads == [("stop", "stop-1", drain_thread_id)]


def test_sdk_shutdown_requires_idle_app_and_runs_on_draining_thread(server):
    control, snapshot, _calls = server
    snapshot.update(mode="douyin", busy=False, queue_depth=0)
    drain_thread_id = threading.get_ident()
    callback_threads = []
    control.command_handler = lambda action, request_id: callback_threads.append(
        (action, request_id, threading.get_ident())
    ) or {"accepted": True, "status": "accepted", "message": "关闭请求已接受"}

    request = _request(
        control,
        "/api/v1/commands",
        method="POST",
        payload={"request_id": "close-1", "action": "shutdown"},
    )
    result = []
    thread = threading.Thread(
        target=lambda: result.append(json.loads(urlopen(request, timeout=2).read()))
    )
    thread.start()
    assert control.wait_for_command(1)
    assert control.drain() == 1
    thread.join(timeout=2)

    assert result == [{"accepted": True, "status": "accepted", "message": "关闭请求已接受"}]
    assert callback_threads == [("shutdown", "close-1", drain_thread_id)]


def test_sdk_shutdown_is_refused_when_busy_or_tasks_are_queued(server):
    control, snapshot, calls = server
    request = _request(
        control,
        "/api/v1/commands",
        method="POST",
        payload={"request_id": "close-busy", "action": "shutdown"},
    )

    snapshot.update(busy=True, queue_depth=0)
    with pytest.raises(HTTPError) as busy_error:
        urlopen(request, timeout=2)
    assert busy_error.value.code == 409
    assert "先结束任务" in json.loads(busy_error.value.read())['reason']

    snapshot.update(busy=False, queue_depth=1)
    queued_request = _request(
        control,
        "/api/v1/commands",
        method="POST",
        payload={"request_id": "close-queued", "action": "shutdown"},
    )
    with pytest.raises(HTTPError) as queued_error:
        urlopen(queued_request, timeout=2)
    assert queued_error.value.code == 409
    assert calls == []


def test_sdk_shutdown_fails_closed_when_queue_depth_is_invalid(server):
    control, snapshot, calls = server
    snapshot.update(busy=False, queue_depth="not-a-number")
    request = _request(
        control,
        "/api/v1/commands",
        method="POST",
        payload={"request_id": "close-invalid-depth", "action": "shutdown"},
    )

    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=2)

    assert error.value.code == 409
    assert "无法确认" in json.loads(error.value.read())["reason"]
    assert calls == []


def test_sdk_deduplicates_same_request_id(server):
    control, snapshot, calls = server
    snapshot.update(mode="douyin", busy=True)
    requests = [
        _request(
            control,
            "/api/v1/commands",
            method="POST",
            payload={"request_id": "duplicate-1", "action": "stop"},
        )
        for _ in range(2)
    ]
    results = []
    threads = [
        threading.Thread(
            target=lambda request=request: results.append(
                json.loads(urlopen(request, timeout=2).read())
            )
        )
        for request in requests
    ]
    for thread in threads:
        thread.start()
    assert control.wait_for_command(1)
    control.drain()
    for thread in threads:
        thread.join(timeout=2)

    assert len(results) == 2
    assert calls == [("stop", "duplicate-1")]


def test_legacy_control_imports_resolve_to_shared_sdk():
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2] / "bilibili-hiatus-analyzer"
    sys.path.insert(0, str(project_root))
    try:
        from backend.remote_control import RemoteControlServer as LegacyServer
    finally:
        sys.path.pop(0)

    assert LegacyServer is RemoteControlServer
