"""Loopback HTTP control server shared by GUI plugins."""

from __future__ import annotations

import hmac
import json
import queue
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping


class StatusSnapshot:
    """Thread-safe mutable status provider for a plugin GUI."""

    def __init__(self, **values: Any) -> None:
        self._lock = threading.RLock()
        self._values = dict(values)

    def update(self, **values: Any) -> None:
        with self._lock:
            self._values.update(values)

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)


@dataclass
class _QueuedCommand:
    request_id: str
    action: str
    response: dict[str, Any] | None = None
    completed: threading.Event = field(default_factory=threading.Event)
    expired: bool = False
    started: bool = False


class _RemoteHandler(BaseHTTPRequestHandler):
    server: "_RemoteServer"

    def do_GET(self) -> None:  # noqa: N802
        control = self.server.control
        if self.path not in {"/api/v1/manifest", "/api/v1/status"}:
            self._write_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        if not control.authorized(self.headers.get("Authorization")):
            self._write_json(HTTPStatus.UNAUTHORIZED, {"detail": "unauthorized"})
            return
        if self.path == "/api/v1/manifest":
            if control.manifest_provider is None:
                self._write_json(HTTPStatus.NOT_FOUND, {"detail": "manifest unavailable"})
                return
            try:
                payload = dict(control.manifest_provider())
            except Exception:
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"detail": "manifest unavailable"})
                return
            self._write_json(HTTPStatus.OK, payload)
            return
        self._write_json(HTTPStatus.OK, control.status_provider())

    def do_POST(self) -> None:  # noqa: N802
        control = self.server.control
        if self.path != "/api/v1/commands":
            self._write_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        if not control.authorized(self.headers.get("Authorization")):
            self._write_json(HTTPStatus.UNAUTHORIZED, {"detail": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 100_000:
                raise ValueError("invalid content length")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("command must be an object")
            request_id = str(payload.get("request_id") or "").strip()
            action = str(payload.get("action") or "").strip()
            if not request_id or not action:
                raise ValueError("request_id and action are required")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._write_json(HTTPStatus.BAD_REQUEST, {"detail": str(error)})
            return

        if action not in {"start", "stop", "shutdown"}:
            self._write_json(HTTPStatus.BAD_REQUEST, {"detail": "unsupported action"})
            return
        reason = control.refusal_reason(action)
        if reason:
            self._write_json(HTTPStatus.CONFLICT, {"reason": reason})
            return
        response = control.submit(_QueuedCommand(request_id, action))
        if response is None:
            self._write_json(
                HTTPStatus.GATEWAY_TIMEOUT,
                {"reason": control.timeout_message},
            )
            return
        self._write_json(HTTPStatus.OK, response)

    def _write_json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
        body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            return

    def log_message(self, _format: str, *_args: Any) -> None:
        return None


class _RemoteServer(ThreadingHTTPServer):
    control: "RemoteControlServer"
    daemon_threads = True
    allow_reuse_address = True


class RemoteControlServer:
    """Authenticated loopback command endpoint for a GUI plugin."""

    def __init__(
        self,
        status_provider: Callable[[], Mapping[str, Any]],
        command_handler: Callable[[str, str], Mapping[str, Any]],
        *,
        token: str,
        host: str = "127.0.0.1",
        port: int = 0,
        manifest_provider: Callable[[], Mapping[str, Any]] | None = None,
        required_ready_fields: tuple[str, ...] = (),
        required_status_values: Mapping[str, tuple[Any, ...]] | None = None,
        refusal_messages: Mapping[str, str] | None = None,
        command_timeout: float = 2.0,
        timeout_message: str = "目标程序未响应控制请求",
        queue_full_message: str = "目标程序控制队列已满",
        shutdown_message: str = "目标程序正在关闭",
    ) -> None:
        if not token:
            raise ValueError("control token is required")
        self.status_provider = status_provider
        self.command_handler = command_handler
        self.token = token
        self.host = host
        self.port = port
        self.manifest_provider = manifest_provider
        self.required_ready_fields = required_ready_fields
        self.required_status_values = {
            key: tuple(values) for key, values in (required_status_values or {}).items()
        }
        self.refusal_messages = dict(refusal_messages or {})
        self.command_timeout = max(float(command_timeout), 0.1)
        self.timeout_message = timeout_message
        self.queue_full_message = queue_full_message
        self.shutdown_message = shutdown_message
        self._queue: queue.Queue[_QueuedCommand] = queue.Queue(maxsize=16)
        self._pending_signal = threading.Event()
        self._request_lock = threading.RLock()
        self._inflight: dict[str, _QueuedCommand] = {}
        self._completed: dict[str, dict[str, Any]] = {}
        self._server: _RemoteServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start_in_thread(self) -> None:
        if self._server is not None:
            return
        server = _RemoteServer((self.host, self.port), _RemoteHandler)
        server.control = self
        self._server = server
        self.port = int(server.server_address[1])
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="plugin-remote-control",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2)
        while True:
            try:
                command = self._queue.get_nowait()
            except queue.Empty:
                break
            command.response = {"accepted": False, "reason": self.shutdown_message}
            command.completed.set()

    def authorized(self, header: str | None) -> bool:
        return bool(header) and hmac.compare_digest(header.strip(), f"Bearer {self.token}")

    def refusal_reason(self, action: str) -> str | None:
        status = dict(self.status_provider())
        if not status.get("gui_running", True):
            return self.refusal_messages.get("gui_running", "目标程序未运行")
        if action == "stop":
            if not status.get("busy"):
                return "当前没有正在运行的任务，无需停止。"
            return None
        if action == "shutdown":
            try:
                queue_depth = int(status.get("queue_depth") or 0)
                if queue_depth < 0:
                    raise ValueError("queue depth cannot be negative")
            except (TypeError, ValueError):
                return "无法确认任务队列状态，请检查目标项目后重试。"
            if status.get("busy") or queue_depth > 0:
                return "当前任务正在运行或排队，请先结束任务。"
            return None
        if action != "start":
            return "unsupported action"
        if status.get("busy"):
            return self.refusal_messages.get("busy", "当前已有任务运行中")
        if not self._queue.empty():
            return self.refusal_messages.get("busy", "当前已有任务正在排队")
        for field in self.required_ready_fields:
            if not status.get(field):
                return self.refusal_messages.get(field, f"当前状态不满足：{field}")
        for field, allowed_values in self.required_status_values.items():
            if status.get(field) not in allowed_values:
                return self.refusal_messages.get(
                    field,
                    f"当前运行模式不支持此操作：{status.get(field) or '未选择'}",
                )
        return None

    def start_refusal_reason(self) -> str | None:
        return self.refusal_reason("start")

    def submit(self, command: _QueuedCommand) -> dict[str, Any] | None:
        with self._request_lock:
            existing = self._inflight.get(command.request_id)
            if existing is not None:
                command = existing
                owner = False
            else:
                cached = self._completed.get(command.request_id)
                if cached is not None:
                    return cached
                self._inflight[command.request_id] = command
                owner = True

        if not owner:
            command.completed.wait(self.command_timeout)
            return command.response

        try:
            self._queue.put_nowait(command)
        except queue.Full:
            self._finish(command, {"accepted": False, "reason": self.queue_full_message})
            return command.response
        self._pending_signal.set()
        if not command.completed.wait(self.command_timeout):
            with self._request_lock:
                if not command.started:
                    command.expired = True
                    timeout_response = {
                        "accepted": False,
                        "status": "rejected",
                        "reason": self.timeout_message,
                    }
                    self._finish(command, timeout_response)
            return None
        return command.response

    def wait_for_command(self, timeout: float | None = None) -> bool:
        return self._pending_signal.wait(timeout)

    def drain(self, max_items: int = 8) -> int:
        handled = 0
        while handled < max_items:
            try:
                command = self._queue.get_nowait()
            except queue.Empty:
                break
            with self._request_lock:
                if command.expired:
                    continue
                command.started = True
            try:
                response = dict(self.command_handler(command.action, command.request_id))
            except Exception as error:
                response = {"accepted": False, "reason": f"GUI 执行失败：{error}"}
            finally:
                self._finish(command, response)
            handled += 1
        if self._queue.empty():
            self._pending_signal.clear()
        return handled

    def _finish(self, command: _QueuedCommand, response: dict[str, Any]) -> None:
        with self._request_lock:
            command.response = response
            self._completed[command.request_id] = response
            self._inflight.pop(command.request_id, None)
            command.completed.set()
