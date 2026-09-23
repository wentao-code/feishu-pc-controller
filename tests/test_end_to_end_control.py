import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

from command_registry import CommandRegistry
from controller_api import ControllerApi
from controller_client import ControlClient
from feishu_bot import BotConfig, ControllerService, discover_plugins, load_plugin_endpoints
from feishu_plugin_sdk.remote_control import RemoteControlServer, StatusSnapshot
from feishu_plugin_sdk.report_client import ReportClient
from plugin_registry import PluginAction, PluginSpec
from report_store import ReportStore


class TargetHandler(BaseHTTPRequestHandler):
    status = {}
    starts = []

    def do_GET(self):  # noqa: N802
        body = json.dumps(self.status).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.starts.append(payload)
        body = json.dumps(
            {
                "request_id": payload["request_id"],
                "accepted": True,
                "status": "accepted",
                "task_id": payload["request_id"],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return None


class ManifestTargetHandler(BaseHTTPRequestHandler):
    token = "secret"
    manifest = {}
    status = {"gui_running": True, "ready": True, "busy": False}
    commands = []

    def _authorized(self):
        return self.headers.get("Authorization") == f"Bearer {self.token}"

    def _write(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if not self._authorized():
            self._write(401, {"detail": "unauthorized"})
        elif self.path == "/api/v1/manifest":
            self._write(200, self.manifest)
        elif self.path == "/api/v1/status":
            self._write(200, self.status)
        else:
            self._write(404, {"detail": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            self._write(401, {"detail": "unauthorized"})
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.commands.append(payload)
        self._write(
            200,
            {
                "request_id": payload["request_id"],
                "accepted": True,
                "status": "accepted",
                "task_id": payload["request_id"],
            },
        )

    def log_message(self, *_args):
        return None


def _start_target(status):
    handler = type("TargetHandlerForTest", (TargetHandler,), {})
    handler.status = status
    handler.starts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, handler


def _start_manifest_target():
    handler = type("ManifestTargetHandlerForTest", (ManifestTargetHandler,), {})
    handler.manifest = {
        "schema_version": "1.0",
        "plugin_id": "manifest_plugin",
        "label": "Manifest 插件",
        "version": "1.0.0",
        "actions": [
            {
                "name": "start",
                "label": "开始 Manifest 任务",
                "aliases": ["Manifest：开始任务"],
            },
            {
                "name": "stop",
                "label": "停止 Manifest 任务",
                "aliases": ["Manifest：停止任务"],
            },
        ],
    }
    handler.status = {"gui_running": True, "ready": True, "busy": False}
    handler.commands = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, handler


def test_two_commands_reach_two_targets_and_report_is_idempotent(tmp_path):
    analyzer, analyzer_thread, analyzer_handler = _start_target(
        {"gui_running": True, "busy": False, "config_locked": True}
    )
    downloader, downloader_thread, downloader_handler = _start_target(
        {"gui_running": True, "busy": False, "ready": True}
    )
    store = ReportStore(tmp_path / "reports.db")
    reports = []
    api = ControllerApi(store, token="secret", port=0, on_report=reports.append)
    api.start_in_thread()
    try:
        config = BotConfig(
            "app",
            "secret",
            "owner",
            control_token="secret",
            main_analyzer_url=f"http://127.0.0.1:{analyzer.server_address[1]}",
            downloader_url=f"http://127.0.0.1:{downloader.server_address[1]}",
        )
        service = ControllerService(
            config,
            clients={
                "main_analyzer": ControlClient(config.main_analyzer_url, "secret"),
                "douyin_downloader": ControlClient(config.downloader_url, "secret"),
            },
        )
        registry = CommandRegistry()

        service.handle_action(registry.resolve("抖音：开始运行"), "fetch-1")
        service.handle_action(registry.resolve("抖音：开始下载"), "download-1")
        service.handle_action(registry.resolve("抖音：开始下载"), "download-1")

        assert [item["request_id"] for item in analyzer_handler.starts] == ["fetch-1"]
        assert [item["request_id"] for item in downloader_handler.starts] == ["download-1"]

        report = {
            "event_id": "download-1:finished",
            "task_id": "download-1",
            "source": "douyin_downloader",
            "task_type": "douyin_download",
            "status": "succeeded",
            "metrics": {"success": 1, "failed": 0, "skipped": 0},
        }
        for _ in range(2):
            request = Request(
                api.base_url + "/api/v1/task-reports",
                data=json.dumps(report).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": "Bearer secret",
                    "Content-Type": "application/json",
                },
            )
            with urlopen(request, timeout=2) as response:
                assert json.loads(response.read())["accepted"] is True
        assert len(reports) == 1
    finally:
        api.stop()
        store.close()
        analyzer.shutdown()
        downloader.shutdown()
        analyzer.server_close()
        downloader.server_close()
        analyzer_thread.join(timeout=2)
        downloader_thread.join(timeout=2)


def test_sdk_plugins_are_discoverable_controllable_and_report_idempotently(tmp_path):
    targets = []
    callbacks = {"analyzer": [], "downloader": []}
    for name, label in (("analyzer", "主程序"), ("downloader", "下载程序")):
        snapshot = StatusSnapshot(gui_running=True, ready=True, busy=False)
        server = RemoteControlServer(
            snapshot.get,
            lambda action, request_id, name=name: callbacks[name].append(
                (action, request_id)
            )
            or {"accepted": True, "status": "accepted", "task_id": request_id},
            token="secret",
            port=0,
            manifest_provider=lambda name=name, label=label: {
                "schema_version": "1.0",
                "plugin_id": name,
                "label": label,
                "version": "1.0.0",
                "protocol": {
                    "manifest": "/api/v1/manifest",
                    "status": "/api/v1/status",
                    "commands": "/api/v1/commands",
                },
                "actions": [
                    {"name": "start", "label": "开始", "aliases": [f"{name} start"]},
                    {"name": "stop", "label": "停止", "aliases": [f"{name} stop"]},
                ],
            },
            required_ready_fields=("ready",),
            command_timeout=1,
        )
        server.start_in_thread()
        targets.append(server)

    store = ReportStore(tmp_path / "reports.db")
    reports = []
    api = ControllerApi(store, token="secret", port=0, on_report=reports.append)
    api.start_in_thread()
    try:
        specs = (
            PluginSpec(
                plugin_id="analyzer",
                label="主程序",
                base_url=targets[0].base_url,
                actions=(PluginAction("start", "开始", ("主程序：开始",)),),
                required_ready_fields=("ready",),
            ),
            PluginSpec(
                plugin_id="downloader",
                label="下载程序",
                base_url=targets[1].base_url,
                actions=(PluginAction("start", "开始", ("下载程序：开始",)),),
                required_ready_fields=("ready",),
            ),
        )
        config = BotConfig("app", "secret", "owner", control_token="secret", plugins=specs)
        clients = {
            spec.plugin_id: ControlClient(spec.base_url, "secret", timeout=1)
            for spec in specs
        }
        service = ControllerService(config, clients=clients)

        for target, expected_name in zip(
            (service.registry.resolve("主程序：开始"), service.registry.resolve("下载程序：开始")),
            ("analyzer", "downloader"),
        ):
            assert target is not None
            result = []
            worker = threading.Thread(
                target=lambda target=target: result.append(
                    service.handle_action(target, f"{expected_name}-request")
                )
            )
            worker.start()
            assert targets[0 if expected_name == "analyzer" else 1].wait_for_command(1)
            assert targets[0 if expected_name == "analyzer" else 1].drain() == 1
            worker.join(timeout=2)
            assert result[0].accepted is True

        for target, plugin_id in zip(targets, ("analyzer", "downloader")):
            with urlopen(
                Request(
                    target.base_url + "/api/v1/manifest",
                    headers={"Authorization": "Bearer secret"},
                ),
                timeout=2,
            ) as response:
                assert json.loads(response.read())["plugin_id"] == plugin_id

        report = {
            "event_id": "analyzer-request:finished",
            "task_id": "analyzer-request",
            "source": "analyzer",
            "task_type": "video_processing",
            "status": "succeeded",
            "metrics": {"success": 1, "failed": 0, "skipped": 0},
        }
        report_client = ReportClient(api.base_url, "secret")
        assert report_client.post(report) is True
        assert report_client.post(report) is True
        assert len(reports) == 1
        assert store.get_task("analyzer-request")["status"] == "succeeded"
    finally:
        api.stop()
        store.close()
        for target in targets:
            target.stop()


def test_manifest_discovery_registers_healthy_plugin_and_isolates_offline_one():
    server, thread, handler = _start_manifest_target()
    try:
        endpoints = load_plugin_endpoints(
            json.dumps(
                [
                    {
                        "id": "manifest_plugin",
                        "url": f"http://127.0.0.1:{server.server_address[1]}",
                        "required_ready_fields": ["ready"],
                    },
                    {
                        "id": "offline_plugin",
                        "url": "http://127.0.0.1:1",
                    },
                ]
            )
        )

        plugins = discover_plugins(endpoints, "secret", timeout=0.2)

        assert [plugin.plugin_id for plugin in plugins] == ["manifest_plugin"]
        config = BotConfig(
            "app",
            "secret",
            "owner",
            control_token="secret",
            plugins=plugins,
            plugins_configured=True,
        )
        service = ControllerService(
            config,
            clients={
                "manifest_plugin": ControlClient(
                    f"http://127.0.0.1:{server.server_address[1]}",
                    "secret",
                    timeout=1,
                )
            },
        )
        target = service.registry.resolve("Manifest：开始任务")

        response = service.handle_action(target, "manifest-request")

        assert response.accepted is True
        assert handler.commands == [
            {"request_id": "manifest-request", "action": "start"}
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
