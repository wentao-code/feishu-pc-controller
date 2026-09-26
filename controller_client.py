"""Authenticated client for the loopback control interfaces."""

from __future__ import annotations

import errno
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from command_registry import ActionSpec
from task_protocol import CommandResponse


class ControlClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        system_not_started: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.system_not_started = system_not_started


class ControlClient:
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

    def get_status(self, target: ActionSpec) -> dict[str, Any]:
        del target
        payload = self._request("GET", "/api/v1/status")
        if not isinstance(payload, dict):
            raise ControlClientError("控制接口返回的状态不是对象")
        return payload

    def start(self, target: ActionSpec, request_id: str) -> CommandResponse:
        return self._command(target, request_id, "start")

    def stop(self, target: ActionSpec, request_id: str) -> CommandResponse:
        return self._command(target, request_id, "stop")

    def shutdown(self, target: ActionSpec, request_id: str) -> CommandResponse:
        return self._command(target, request_id, "shutdown")

    def _command(
        self, target: ActionSpec, request_id: str, action: str
    ) -> CommandResponse:
        payload = self._request(
            "POST",
            "/api/v1/commands",
            {"request_id": request_id, "action": action},
        )
        if not isinstance(payload, dict):
            raise ControlClientError("控制接口返回的启动结果不是对象")
        try:
            return CommandResponse(
                request_id=str(payload.get("request_id") or request_id),
                accepted=bool(payload.get("accepted")),
                status=str(payload.get("status") or "rejected"),
                message=str(payload.get("message") or ""),
                reason=str(payload.get("reason") or "") or None,
                task_id=str(payload.get("task_id") or "") or None,
            )
        except ValueError as error:
            raise ControlClientError(f"控制接口返回了无效的启动状态: {error}") from error

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            detail = self._error_detail(raw) or f"HTTP {error.code}"
            raise ControlClientError(detail, status_code=error.code) from error
        except URLError as error:
            if self._is_connection_refused(error.reason):
                raise ControlClientError(
                    "系统未启动",
                    system_not_started=True,
                ) from error
            raise ControlClientError(f"控制接口不可用: {error.reason}") from error
        except OSError as error:
            raise ControlClientError(f"控制接口请求失败: {error}") from error
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ControlClientError("控制接口返回了无效 JSON") from error

    @staticmethod
    def _error_detail(raw: bytes) -> str | None:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return str(payload.get("reason") or payload.get("detail") or "").strip() or None

    @staticmethod
    def _is_connection_refused(reason: object) -> bool:
        if not isinstance(reason, OSError):
            return False
        return (
            isinstance(reason, ConnectionRefusedError)
            or reason.errno == errno.ECONNREFUSED
            or getattr(reason, "winerror", None) == 10061
        )
