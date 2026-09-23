"""Authenticated client for discovering a plugin capability manifest."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from feishu_plugin_sdk.manifest import PluginManifest


class ManifestClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ManifestClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 5.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = max(float(timeout), 0.1)
        self.opener = opener

    def fetch(self) -> PluginManifest:
        request = Request(
            self.base_url + "/api/v1/manifest",
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            detail = self._error_detail(raw) or f"HTTP {error.code}"
            raise ManifestClientError(detail, status_code=error.code) from error
        except URLError as error:
            raise ManifestClientError(f"控制接口不可用: {error.reason}") from error
        except OSError as error:
            raise ManifestClientError(f"控制接口请求失败: {error}") from error

        try:
            payload = json.loads(raw.decode("utf-8"))
            return PluginManifest.from_json(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ManifestClientError("Manifest 接口返回了无效 JSON") from error
        except (TypeError, ValueError) as error:
            raise ManifestClientError(f"Manifest 内容无效: {error}") from error

    @staticmethod
    def _error_detail(raw: bytes) -> str | None:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return str(payload.get("reason") or payload.get("detail") or "").strip() or None
