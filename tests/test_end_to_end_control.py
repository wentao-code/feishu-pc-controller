import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

from command_registry import CommandRegistry
from controller_api import ControllerApi
from controller_client import ControlClient
from feishu_bot import BotConfig, ControllerService
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


def _start_target(status):
    handler = type("TargetHandlerForTest", (TargetHandler,), {})
    handler.status = status
    handler.starts = []
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
