import json
from urllib.error import HTTPError, URLError

import pytest

from manifest_client import ManifestClient, ManifestClientError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

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


def _manifest():
    return {
        "schema_version": "1.0",
        "plugin_id": "video_tools",
        "label": "视频工具",
        "version": "1.0.0",
        "actions": [
            {
                "name": "start",
                "label": "开始处理",
                "aliases": ["视频工具：开始处理"],
            }
        ],
    }


def test_fetch_uses_bearer_auth_and_returns_validated_manifest():
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(_manifest())

    client = ManifestClient("http://127.0.0.1:8763/", "secret", timeout=2, opener=opener)

    manifest = client.fetch()

    request, timeout = calls[0]
    assert request.get_header("Authorization") == "Bearer secret"
    assert request.full_url == "http://127.0.0.1:8763/api/v1/manifest"
    assert timeout == 2
    assert manifest.plugin_id == "video_tools"
    assert manifest.actions[0]["name"] == "start"


def test_fetch_maps_http_error_detail():
    def opener(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            FakeResponse({"detail": "unauthorized"}),
        )

    client = ManifestClient("http://127.0.0.1:8763", "wrong", opener=opener)

    with pytest.raises(ManifestClientError, match="unauthorized") as error:
        client.fetch()

    assert error.value.status_code == 401


def test_fetch_maps_url_error_and_invalid_manifest():
    def unavailable(_request, **_kwargs):
        raise URLError("connection refused")

    client = ManifestClient("http://127.0.0.1:8763", "secret", opener=unavailable)
    with pytest.raises(ManifestClientError, match="控制接口不可用"):
        client.fetch()

    invalid_client = ManifestClient(
        "http://127.0.0.1:8763",
        "secret",
        opener=lambda _request, **_kwargs: FakeResponse({"plugin_id": "missing-actions"}),
    )
    with pytest.raises(ManifestClientError, match="manifest actions"):
        invalid_client.fetch()
