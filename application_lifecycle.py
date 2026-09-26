"""Allowlisted application launch and graceful close operations."""

from __future__ import annotations

import ipaddress
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

from command_registry import ActionSpec
from controller_client import ControlClient, ControlClientError
from task_protocol import CommandResponse


_GUI_PROJECTS = frozenset(
    {
        "bilibili-hiatus-analyzer",
        "douyin-downloader-main",
        "local_video_renamer",
    }
)
_QUARK_PROJECT = "quark_file_management"
_CLOSE_BUSY_MESSAGE = "当前任务正在运行或排队，请先结束任务。"


class ApplicationLifecycleManager:
    """Start known local entrypoints and close only through safe project paths."""

    def __init__(
        self,
        *,
        project_roots: Mapping[str, Path],
        clients: Mapping[str, ControlClient],
        control_token: str,
        quark_web_url: str = "http://127.0.0.1:8501",
        quark_control_port: int = 8764,
        process_factory: Callable[..., Any] = subprocess.Popen,
        quark_web_probe: Callable[[], bool] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        startup_timeout: float = 20.0,
        poll_interval: float = 0.25,
    ) -> None:
        self.project_roots = {key: Path(value).resolve() for key, value in project_roots.items()}
        self.clients = dict(clients)
        self.control_token = str(control_token or "")
        self.quark_web_url = self._validate_quark_web_url(quark_web_url)
        self.quark_control_port = int(quark_control_port)
        self.process_factory = process_factory
        self.quark_web_probe = quark_web_probe or self._probe_quark_web
        self.sleeper = sleeper
        self.startup_timeout = max(0.0, float(startup_timeout))
        self.poll_interval = max(0.01, float(poll_interval))
        self._owned_processes: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _validate_quark_web_url(value: str) -> str:
        try:
            parsed = urlsplit(str(value).strip())
            host = (parsed.hostname or "").lower()
            port = parsed.port
            is_loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError as error:
            raise ValueError("Quark Web URL must be a loopback HTTP origin") from error
        if (
            parsed.scheme != "http"
            or not is_loopback
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError("Quark Web URL must be a loopback HTTP origin")
        netloc = parsed.netloc.rstrip("/")
        if not netloc:
            raise ValueError("Quark Web URL must be a loopback HTTP origin")
        return urlunsplit(("http", netloc, "", "", ""))

    def start(self, project_id: str, request_id: str) -> CommandResponse:
        if project_id not in _GUI_PROJECTS | {_QUARK_PROJECT}:
            return self._rejected(request_id, "未配置该项目的固定启动入口。")
        if project_id == _QUARK_PROJECT:
            return self._start_quark(request_id)

        status, error = self._plugin_status(project_id)
        if error is not None and not error.system_not_started:
            return self._rejected(request_id, f"无法确认项目状态：{error}")
        if status is not None:
            if status.get("gui_running"):
                return self._accepted(request_id, "项目已经在运行。")
            return self._rejected(request_id, "项目控制接口在线，但 GUI 尚未就绪。")

        command, cwd, error_message = self._gui_launch_command(project_id)
        if error_message:
            return self._rejected(request_id, error_message)
        try:
            self._spawn(command, cwd)
        except (OSError, ValueError) as error:
            return self._rejected(request_id, f"启动项目失败：{error}")

        ready, probe_error = self._wait_for_plugin(project_id)
        if ready:
            return self._accepted(request_id, "项目已启动。")
        message = f"项目启动后未能通过就绪检查（{self.startup_timeout:g} 秒）。"
        if probe_error:
            message += f" {probe_error}"
        return self._rejected(request_id, message)

    def close(self, project_id: str, request_id: str) -> CommandResponse:
        if project_id == _QUARK_PROJECT:
            return self._close_quark(request_id)
        if project_id not in _GUI_PROJECTS:
            return self._rejected(request_id, "未配置该项目的关闭入口。")

        status, error = self._plugin_status(project_id)
        if error is not None:
            reason = "系统未启动" if error.system_not_started else f"无法确认项目状态：{error}"
            return self._rejected(request_id, reason)
        if status is None or not status.get("gui_running"):
            return self._rejected(request_id, "系统未启动")
        if self._busy(status):
            return self._rejected(request_id, _CLOSE_BUSY_MESSAGE)

        client = self.clients.get(project_id)
        if client is None:
            return self._rejected(request_id, "项目关闭接口未配置。")
        target = ActionSpec("application.close", project_id, "close", "关闭项目")
        try:
            return client.shutdown(target, request_id)
        except ControlClientError as error:
            return self._rejected(request_id, f"项目关闭请求失败：{error}")

    def _start_quark(self, request_id: str) -> CommandResponse:
        if self.quark_web_probe():
            return self._accepted(request_id, "项目已经在运行。")
        owned = self._owned_processes.setdefault(_QUARK_PROJECT, {})
        web_process = owned.get("web")
        if web_process is not None:
            if web_process.poll() is None:
                return self._rejected(
                    request_id,
                    "Quark Web 仍由控制器跟踪，未重复启动。",
                )
            owned.pop("web", None)
        root = self.project_roots.get(_QUARK_PROJECT)
        launcher = root / "start_web.bat" if root else None
        if launcher is None or not launcher.is_file():
            return self._rejected(request_id, "未找到 Quark Web 启动脚本 start_web.bat。")

        control_status, control_error = self._plugin_status(_QUARK_PROJECT)
        if control_status is None and control_error is not None:
            if not control_error.system_not_started:
                return self._rejected(request_id, f"Quark 控制服务状态异常：{control_error}")
            control_process = owned.get("control")
            if control_process is not None:
                if control_process.poll() is None:
                    return self._rejected(
                        request_id,
                        "Quark 状态服务仍由控制器跟踪，未重复启动。",
                    )
                owned.pop("control", None)
            try:
                control_process = self._spawn(
                    [
                        sys.executable,
                        "-m",
                        "quark_manager.control_server",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(self.quark_control_port),
                    ],
                    root,
                    extra_env={"FEISHU_CONTROL_TOKEN": self.control_token},
                )
                owned["control"] = control_process
            except (OSError, ValueError) as error:
                return self._rejected(request_id, f"启动 Quark 状态服务失败：{error}")
            if not self._wait_for_plugin(_QUARK_PROJECT)[0]:
                self._stop_owned_control(owned)
                return self._rejected(request_id, "Quark 状态服务未能就绪，未启动 Web。")
        elif control_status is not None and not control_status.get("gui_running", True):
            return self._rejected(request_id, "Quark 控制服务在线，但状态尚未就绪。")

        try:
            owned["web"] = self._spawn(["cmd.exe", "/c", str(launcher)], root)
        except (OSError, ValueError) as error:
            self._stop_owned_control(owned)
            return self._rejected(request_id, f"启动 Quark Web 失败：{error}")

        if self._wait_for_quark_web():
            return self._accepted(request_id, "项目已启动。")
        process = owned.get("web")
        if process is not None:
            self._signal_process(process)
            if process.poll() is not None:
                owned.pop("web", None)
        self._stop_owned_control(owned)
        return self._rejected(request_id, "Quark Web 启动后未能通过就绪检查。")

    def _close_quark(self, request_id: str) -> CommandResponse:
        if not self.quark_web_probe():
            return self._rejected(request_id, "系统未启动")
        owned = self._owned_processes.get(_QUARK_PROJECT, {})
        web_process = owned.get("web")
        if web_process is None or web_process.poll() is not None:
            return self._rejected(
                request_id,
                "Quark Web 不是由当前控制器启动，无法安全关闭。",
            )

        status, error = self._plugin_status(_QUARK_PROJECT)
        if error is not None or status is None:
            return self._rejected(
                request_id,
                "无法确认 Quark 任务状态，未关闭项目。",
            )
        if self._busy(status):
            return self._rejected(request_id, _CLOSE_BUSY_MESSAGE)

        if not self._signal_process(web_process):
            return self._rejected(request_id, "未能向 Quark Web 发送安全退出信号。")
        if not self._wait_until(lambda: not self.quark_web_probe()):
            return self._rejected(
                request_id,
                "已请求 Quark Web 退出，但服务仍在运行；未强制结束进程。",
            )
        owned.pop("web", None)
        self._stop_owned_control(owned)
        if not owned:
            self._owned_processes.pop(_QUARK_PROJECT, None)
        return self._accepted(request_id, "项目已关闭。")

    def _gui_launch_command(self, project_id: str):
        root = self.project_roots.get(project_id)
        if root is None:
            return None, None, "未配置该项目根目录。"
        if project_id == "bilibili-hiatus-analyzer":
            launcher = root / "start_gui.bat"
            command = ["cmd.exe", "/c", str(launcher)]
        elif project_id == "douyin-downloader-main":
            launcher = root / "run.py"
            command = [sys.executable, str(launcher), "--gui"]
        else:
            launcher = root / "start_vidnorm.bat"
            command = ["cmd.exe", "/c", str(launcher)]
        if not launcher.is_file():
            return None, None, f"未找到项目启动入口：{launcher}"
        return command, root, None

    def _plugin_status(self, project_id: str):
        client = self.clients.get(project_id)
        if client is None:
            return None, ControlClientError("项目控制接口未配置")
        target = ActionSpec("system.status", project_id, "status", project_id)
        try:
            return client.get_status(target), None
        except ControlClientError as error:
            return None, error

    def _wait_for_plugin(self, project_id: str) -> tuple[bool, str | None]:
        last_error = None

        def ready() -> bool:
            nonlocal last_error
            status, error = self._plugin_status(project_id)
            if error is not None:
                last_error = str(error)
                return False
            last_error = None
            return bool(status and status.get("gui_running", True))

        succeeded = self._wait_until(ready)
        return succeeded, last_error

    def _wait_for_quark_web(self) -> bool:
        return self._wait_until(self.quark_web_probe)

    def _wait_until(self, predicate: Callable[[], bool]) -> bool:
        deadline = time.monotonic() + self.startup_timeout
        while True:
            if predicate():
                return True
            if time.monotonic() >= deadline:
                return False
            self.sleeper(min(self.poll_interval, max(0.0, deadline - time.monotonic())))

    def _spawn(
        self,
        command: list[str],
        cwd: Path,
        *,
        extra_env: Mapping[str, str] | None = None,
    ):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        options = {}
        if extra_env:
            options["env"] = {**os.environ, **extra_env}
        return self.process_factory(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
            **options,
        )

    @staticmethod
    def _signal_process(process: Any) -> bool:
        if process.poll() is not None:
            return True
        signal_value = getattr(signal, "CTRL_BREAK_EVENT", None)
        if signal_value is None:
            signal_value = signal.SIGTERM
        try:
            process.send_signal(signal_value)
        except (OSError, ValueError, AttributeError):
            return False
        return True

    def _stop_owned_control(self, owned: dict[str, Any]) -> None:
        process = owned.get("control")
        if process is not None:
            self._signal_process(process)
            if process.poll() is not None:
                owned.pop("control", None)

    def _probe_quark_web(self) -> bool:
        try:
            with urlopen(self.quark_web_url + "/_stcore/health", timeout=0.5) as response:
                return response.status == 200
        except (OSError, URLError, TimeoutError):
            return False

    @staticmethod
    def _busy(status: Mapping[str, Any]) -> bool:
        if status.get("busy"):
            return True
        try:
            return int(status.get("queue_depth") or 0) > 0
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _accepted(request_id: str, message: str) -> CommandResponse:
        return CommandResponse(
            request_id=request_id,
            accepted=True,
            status="accepted",
            message=message,
        )

    @staticmethod
    def _rejected(request_id: str, reason: str) -> CommandResponse:
        return CommandResponse(
            request_id=request_id,
            accepted=False,
            status="rejected",
            reason=reason,
        )
