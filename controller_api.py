"""Loopback HTTP API used by business applications to submit task reports."""

from __future__ import annotations

import hmac
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from report_store import ReportStore
from task_protocol import TaskReport


class _RequestHandler(BaseHTTPRequestHandler):
    server: "_ApiServer"

    def do_GET(self) -> None:  # noqa: N802
        api = self.server.controller_api
        if self.path not in {"/api/v1/health", "/api/v1/system/status"}:
            self._write_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        if not api.authorized(self.headers.get("Authorization")):
            self._write_json(HTTPStatus.UNAUTHORIZED, {"detail": "unauthorized"})
            return
        if self.path == "/api/v1/health":
            payload = {"ok": True, "controller_running": True}
        else:
            payload = {"ok": True, "tasks": api.store.latest_tasks()}
        self._write_json(HTTPStatus.OK, payload)

    def do_POST(self) -> None:  # noqa: N802
        api = self.server.controller_api
        if self.path != "/api/v1/task-reports":
            self._write_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        if not api.authorized(self.headers.get("Authorization")):
            self._write_json(HTTPStatus.UNAUTHORIZED, {"detail": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 1_000_000:
                raise ValueError("invalid content length")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("report must be an object")
            report = TaskReport.from_json(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._write_json(HTTPStatus.BAD_REQUEST, {"detail": str(error)})
            return

        inserted = api.store.record(report)
        if inserted and api.on_report is not None:
            try:
                api.on_report(report)
            except Exception:
                # Notification failures must not make a committed report retry forever.
                pass
        self._write_json(
            HTTPStatus.OK,
            {
                "accepted": True,
                "duplicate": not inserted,
                "event_id": report.event_id,
            },
        )

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: Any) -> None:
        return None


class _ApiServer(ThreadingHTTPServer):
    controller_api: "ControllerApi"
    daemon_threads = True
    allow_reuse_address = True


class ControllerApi:
    def __init__(
        self,
        store: ReportStore,
        *,
        token: str,
        host: str = "127.0.0.1",
        port: int = 0,
        on_report: Callable[[TaskReport], None] | None = None,
    ) -> None:
        if not token:
            raise ValueError("controller token is required")
        self.store = store
        self.token = token
        self.host = host
        self.port = port
        self.on_report = on_report
        self._server: _ApiServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start_in_thread(self) -> None:
        if self._server is not None:
            return
        server = _ApiServer((self.host, self.port), _RequestHandler)
        server.controller_api = self
        self._server = server
        self.port = int(server.server_address[1])
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="feishu-controller-api",
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

    def authorized(self, header: str | None) -> bool:
        expected = f"Bearer {self.token}"
        return bool(header) and hmac.compare_digest(header.strip(), expected)
