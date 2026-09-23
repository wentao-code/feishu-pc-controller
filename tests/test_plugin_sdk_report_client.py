import json

from feishu_plugin_sdk.report_client import ReportClient


class FakeResponse:
    def read(self):
        return b"{}"

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_sdk_report_client_posts_authenticated_json():
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    client = ReportClient("http://127.0.0.1:8760", "secret", opener=opener)

    assert client.post({"event_id": "event-1", "status": "cancelled"}) is True
    request, timeout = calls[0]
    assert request.get_header("Authorization") == "Bearer secret"
    assert json.loads(request.data) == {
        "event_id": "event-1",
        "status": "cancelled",
    }
    assert timeout == 3.0


def test_sdk_report_client_returns_false_without_configuration():
    assert ReportClient("", "").post({"event_id": "event-1"}) is False


def test_legacy_report_import_resolves_to_shared_sdk():
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2] / "bilibili-hiatus-analyzer"
    sys.path.insert(0, str(project_root))
    try:
        from backend.report_client import ReportClient as LegacyClient
    finally:
        sys.path.pop(0)

    assert LegacyClient is ReportClient
