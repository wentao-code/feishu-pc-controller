import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from controller_api import ControllerApi
from report_store import ReportStore


@pytest.fixture
def api(tmp_path):
    store = ReportStore(tmp_path / "reports.db")
    received = []
    server = ControllerApi(store, token="secret", on_report=received.append)
    server.start_in_thread()
    try:
        yield server, received
    finally:
        server.stop()
        store.close()


def _request(api, path, *, method="GET", payload=None, token="secret"):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    if body:
        headers["Content-Type"] = "application/json"
    request = Request(api.base_url + path, data=body, method=method, headers=headers)
    return urlopen(request, timeout=2)


def _report(event_id="event-1"):
    return {
        "event_id": event_id,
        "task_id": "task-1",
        "source": "main_analyzer",
        "task_type": "douyin_fetch",
        "status": "succeeded",
        "elapsed_seconds": 12,
        "metrics": {"success": 2, "failed": 0, "skipped": 1},
    }


def test_health_endpoint_returns_controller_status(api):
    server, _received = api

    with _request(server, "/api/v1/health") as response:
        payload = json.loads(response.read())

    assert payload["ok"] is True
    assert payload["controller_running"] is True


def test_report_is_accepted_once_and_duplicate_is_deduplicated(api):
    server, received = api

    with _request(server, "/api/v1/task-reports", method="POST", payload=_report()) as response:
        first = json.loads(response.read())
    with _request(server, "/api/v1/task-reports", method="POST", payload=_report()) as response:
        second = json.loads(response.read())

    assert first == {"accepted": True, "duplicate": False, "event_id": "event-1"}
    assert second == {"accepted": True, "duplicate": True, "event_id": "event-1"}
    assert len(received) == 1


def test_report_requires_token(api):
    server, _received = api

    with pytest.raises(HTTPError) as error:
        _request(server, "/api/v1/task-reports", method="POST", payload=_report(), token="wrong")

    assert error.value.code == 401


def test_malformed_report_returns_bad_request(api):
    server, _received = api

    with pytest.raises(HTTPError) as error:
        _request(
            server,
            "/api/v1/task-reports",
            method="POST",
            payload={"event_id": "only-id"},
        )

    assert error.value.code == 400
