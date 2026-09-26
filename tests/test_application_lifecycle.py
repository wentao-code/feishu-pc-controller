from pathlib import Path

import pytest

from controller_client import ControlClientError
from application_lifecycle import ApplicationLifecycleManager


class FakeClient:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.last_status = None
        self.shutdown_calls = []

    def get_status(self, _target=None):
        if self.statuses:
            value = self.statuses.pop(0)
            if isinstance(value, Exception):
                raise value
            self.last_status = value
        if self.last_status is None:
            raise ControlClientError("系统未启动", system_not_started=True)
        return dict(self.last_status)

    def shutdown(self, _target, request_id):
        self.shutdown_calls.append(request_id)
        return type(
            "Response",
            (),
            {"accepted": True, "status": "accepted", "message": "项目关闭请求已接受。", "reason": None},
        )()


class FakeProcess:
    def __init__(self, on_signal=None):
        self.signals = []
        self._on_signal = on_signal
        self._returncode = None

    def poll(self):
        return self._returncode

    def send_signal(self, value):
        self.signals.append(value)
        if self._on_signal is not None:
            self._on_signal()
        self._returncode = 0


def test_gui_launch_uses_fixed_entrypoint_and_waits_until_status_is_ready(tmp_path):
    root = tmp_path / "analyzer"
    root.mkdir()
    launcher = root / "start_gui.bat"
    launcher.touch()
    client = FakeClient(
        [
            ControlClientError("系统未启动", system_not_started=True),
            {"gui_running": True, "busy": False},
        ]
    )
    spawned = []

    def popen(command, **kwargs):
        spawned.append((command, kwargs))
        return FakeProcess()

    manager = ApplicationLifecycleManager(
        project_roots={"bilibili-hiatus-analyzer": root},
        clients={"bilibili-hiatus-analyzer": client},
        control_token="secret",
        process_factory=popen,
        sleeper=lambda _seconds: None,
        startup_timeout=0.02,
    )

    response = manager.start("bilibili-hiatus-analyzer", "start-1")

    command, kwargs = spawned[0]
    assert Path(command[-1]) == launcher
    assert kwargs["cwd"] == str(root)
    assert response.accepted is True
    assert response.message == "项目已启动。"


def test_start_does_not_launch_a_project_that_is_already_healthy(tmp_path):
    root = tmp_path / "analyzer"
    root.mkdir()
    (root / "start_gui.bat").touch()
    spawned = []
    manager = ApplicationLifecycleManager(
        project_roots={"bilibili-hiatus-analyzer": root},
        clients={"bilibili-hiatus-analyzer": FakeClient([{"gui_running": True}])},
        control_token="secret",
        process_factory=lambda *args, **kwargs: spawned.append((args, kwargs)),
    )

    response = manager.start("bilibili-hiatus-analyzer", "start-2")

    assert response.accepted is True
    assert response.message == "项目已经在运行。"
    assert spawned == []


@pytest.mark.parametrize(
    ("project_id", "entrypoint"),
    [
        ("douyin-downloader-main", "run.py"),
        ("local_video_renamer", "start_vidnorm.bat"),
    ],
)
def test_gui_projects_use_their_fixed_launch_entrypoint(tmp_path, project_id, entrypoint):
    root = tmp_path / project_id
    root.mkdir()
    launcher = root / entrypoint
    launcher.touch()
    client = FakeClient(
        [
            ControlClientError("系统未启动", system_not_started=True),
            {"gui_running": True, "busy": False},
        ]
    )
    spawned = []
    manager = ApplicationLifecycleManager(
        project_roots={project_id: root},
        clients={project_id: client},
        control_token="secret",
        process_factory=lambda command, **kwargs: spawned.append(command) or FakeProcess(),
        sleeper=lambda _seconds: None,
        startup_timeout=0.02,
    )

    response = manager.start(project_id, "start-fixed")

    assert response.accepted is True
    assert str(launcher) in spawned[0]


def test_quark_close_refuses_a_web_server_not_started_by_this_controller(tmp_path):
    root = tmp_path / "quark"
    root.mkdir()
    (root / "start_web.bat").touch()
    spawned = []
    manager = ApplicationLifecycleManager(
        project_roots={"quark_file_management": root},
        clients={"quark_file_management": FakeClient([])},
        control_token="secret",
        quark_web_probe=lambda: True,
        process_factory=lambda *args, **kwargs: spawned.append((args, kwargs)),
    )

    response = manager.close("quark_file_management", "close-unmanaged")

    assert response.accepted is False
    assert "控制器启动" in response.reason
    assert spawned == []


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:8501",
        "http://127.0.0.1:8501/proxy",
        "http://user:password@127.0.0.1:8501",
        "https://127.0.0.1:8501",
    ],
)
def test_quark_web_url_must_be_a_plain_loopback_http_origin(url):
    with pytest.raises(ValueError, match="loopback"):
        ApplicationLifecycleManager(
            project_roots={},
            clients={},
            control_token="secret",
            quark_web_url=url,
        )


def test_quark_lifecycle_starts_web_and_refuses_close_while_queue_is_busy(tmp_path):
    root = tmp_path / "quark"
    root.mkdir()
    (root / "start_web.bat").touch()
    web_state = {"running": False}
    control_client = FakeClient(
        [
            ControlClientError("系统未启动", system_not_started=True),
            {"gui_running": True, "busy": False, "queue_depth": 0},
            {"gui_running": True, "busy": True, "queue_depth": 0},
        ]
    )
    spawned = []

    def popen(command, **kwargs):
        is_web = "start_web.bat" in str(command)
        process = FakeProcess(on_signal=lambda: web_state.update(running=False) if is_web else None)
        spawned.append((command, kwargs, process))
        if is_web:
            web_state["running"] = True
        return process

    manager = ApplicationLifecycleManager(
        project_roots={"quark_file_management": root},
        clients={"quark_file_management": control_client},
        control_token="secret",
        quark_web_probe=lambda: web_state["running"],
        process_factory=popen,
        sleeper=lambda _seconds: None,
        startup_timeout=0.02,
    )

    started = manager.start("quark_file_management", "quark-start")
    closed = manager.close("quark_file_management", "quark-close")

    assert started.accepted is True
    assert any("start_web.bat" in str(item[0]) for item in spawned)
    assert closed.accepted is False
    assert "先结束任务" in closed.reason
    assert all(not item[2].signals for item in spawned)


def test_quark_web_close_sends_graceful_signal_only_to_owned_process(tmp_path):
    root = tmp_path / "quark"
    root.mkdir()
    (root / "start_web.bat").touch()
    web_state = {"running": False}
    control_client = FakeClient(
        [
            ControlClientError("系统未启动", system_not_started=True),
            {"gui_running": True, "busy": False, "queue_depth": 0},
            {"gui_running": True, "busy": False, "queue_depth": 0},
        ]
    )
    spawned = []

    def popen(command, **kwargs):
        is_web = "start_web.bat" in str(command)
        process = FakeProcess(on_signal=lambda: web_state.update(running=False) if is_web else None)
        spawned.append((command, kwargs, process))
        if is_web:
            web_state["running"] = True
        return process

    manager = ApplicationLifecycleManager(
        project_roots={"quark_file_management": root},
        clients={"quark_file_management": control_client},
        control_token="secret",
        quark_web_probe=lambda: web_state["running"],
        process_factory=popen,
        sleeper=lambda _seconds: None,
        startup_timeout=0.02,
    )

    started = manager.start("quark_file_management", "quark-start")
    closed = manager.close("quark_file_management", "quark-close")

    control_command = next(item for item in spawned if "control_server" in str(item[0]))
    web_process = next(item[2] for item in spawned if "start_web.bat" in str(item[0]))
    assert started.accepted is True
    assert closed.accepted is True
    assert web_process.signals
    assert "secret" not in str(control_command[0])
    assert control_command[1]["env"]["FEISHU_CONTROL_TOKEN"] == "secret"


def test_quark_start_timeout_keeps_ownership_when_graceful_signal_does_not_exit(tmp_path):
    root = tmp_path / "quark"
    root.mkdir()
    (root / "start_web.bat").touch()
    control_client = FakeClient(
        [
            ControlClientError("系统未启动", system_not_started=True),
            {"gui_running": True, "busy": False, "queue_depth": 0},
        ]
    )
    processes = []

    def popen(command, **_kwargs):
        process = FakeProcess()
        if "start_web.bat" in str(command):
            process.send_signal = lambda value: process.signals.append(value)
        processes.append((command, process))
        return process

    manager = ApplicationLifecycleManager(
        project_roots={"quark_file_management": root},
        clients={"quark_file_management": control_client},
        control_token="secret",
        quark_web_probe=lambda: False,
        process_factory=popen,
        startup_timeout=0,
    )

    response = manager.start("quark_file_management", "quark-timeout")

    web_process = next(process for command, process in processes if "start_web.bat" in str(command))
    assert response.accepted is False
    assert web_process.signals
    assert manager._owned_processes["quark_file_management"]["web"] is web_process

    retry = manager.start("quark_file_management", "quark-timeout-retry")

    assert retry.accepted is False
    assert "仍由控制器跟踪" in retry.reason
    assert sum("start_web.bat" in str(command) for command, _ in processes) == 1


def test_quark_control_start_timeout_keeps_ownership_and_prevents_duplicate(tmp_path):
    root = tmp_path / "quark"
    root.mkdir()
    (root / "start_web.bat").touch()
    unavailable = ControlClientError("系统未启动", system_not_started=True)
    client = FakeClient([unavailable, unavailable])
    processes = []

    def popen(command, **_kwargs):
        process = FakeProcess()
        process.send_signal = lambda value: process.signals.append(value)
        processes.append((command, process))
        return process

    manager = ApplicationLifecycleManager(
        project_roots={"quark_file_management": root},
        clients={"quark_file_management": client},
        control_token="secret",
        quark_web_probe=lambda: False,
        process_factory=popen,
        startup_timeout=0,
    )

    first = manager.start("quark_file_management", "control-timeout")
    retry = manager.start("quark_file_management", "control-timeout-retry")

    control_processes = [process for command, process in processes if "control_server" in str(command)]
    assert first.accepted is False
    assert retry.accepted is False
    assert "仍由控制器跟踪" in retry.reason
    assert len(control_processes) == 1
    assert manager._owned_processes["quark_file_management"]["control"] is control_processes[0]
