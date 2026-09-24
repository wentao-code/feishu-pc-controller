import threading

from command_registry import CommandRegistry
from feishu_bot import BotConfig, ControllerService, command_for_message
from plugin_registry import PluginAction, PluginSpec
from task_protocol import CommandResponse


class FakeClient:
    def __init__(self, status, response=None):
        self.status = status
        self.response = response or CommandResponse("req-1", True, "accepted", task_id="task-1")
        self.started = []
        self.stopped = []

    def get_status(self, _target):
        return dict(self.status)

    def start(self, _target, request_id):
        self.started.append(request_id)
        return self.response

    def stop(self, _target, request_id):
        self.stopped.append(request_id)
        return CommandResponse(
            request_id=request_id,
            accepted=True,
            status="accepted",
            message="已提交停止请求",
            task_id="task-1",
        )


def _config():
    return BotConfig("app", "secret", "owner", control_token="token")


def test_feishu_start_commands_map_to_stable_commands():
    assert command_for_message("抖音：开始运行") == "douyin_fetch_start"
    assert command_for_message("抖音：开始下载") == "douyin_download_start"
    assert command_for_message("抖音：停止运行") == "douyin_fetch_stop"
    assert command_for_message("抖音：停止下载") == "douyin_download_stop"
    assert command_for_message("抖音：状态") == "douyin_fetch_status"
    assert command_for_message("抖音下载：状态") == "douyin_download_status"


def test_service_rejects_analyzer_when_configuration_is_unlocked():
    client = FakeClient({"gui_running": True, "busy": False, "config_locked": False})
    service = ControllerService(_config(), clients={"bilibili-hiatus-analyzer": client})
    target = CommandRegistry().resolve("抖音：开始运行")

    response = service.handle_action(target, "req-1")

    assert response.accepted is False
    assert response.reason == "当前配置未锁定，请先在主程序中锁定配置"
    assert client.started == []


def test_service_starts_ready_downloader_once():
    client = FakeClient({"gui_running": True, "busy": False, "ready": True})
    service = ControllerService(_config(), clients={"douyin-downloader-main": client})
    target = CommandRegistry().resolve("抖音：开始下载")

    response = service.handle_action(target, "req-1")

    assert response.accepted is True
    assert client.started == ["req-1"]


def test_service_stops_running_downloader():
    client = FakeClient({"gui_running": True, "busy": True, "ready": True})
    service = ControllerService(_config(), clients={"douyin-downloader-main": client})
    target = CommandRegistry().resolve("抖音：停止下载")

    response = service.handle_action(target, "stop-1")

    assert response.accepted is True
    assert response.message == "已提交停止请求"
    assert client.stopped == ["stop-1"]


def test_service_reads_plugin_status_without_sending_a_command():
    client = FakeClient({"gui_running": True, "busy": False, "ready": True})
    service = ControllerService(_config(), clients={"douyin-downloader-main": client})
    target = CommandRegistry().resolve("抖音下载：状态")

    response = service.handle_action(target, "status-1")

    assert response.accepted is True
    assert response.message == "douyin-downloader-main：已启动，当前空闲"
    assert client.started == []
    assert client.stopped == []


def test_service_status_reports_busy_without_rejecting_or_stopping():
    client = FakeClient({"gui_running": True, "busy": True, "ready": True, "task_id": "task-7"})
    service = ControllerService(_config(), clients={"douyin-downloader-main": client})
    target = CommandRegistry().resolve("抖音下载：状态")

    response = service.handle_action(target, "status-busy")

    assert response.accepted is True
    assert response.message == "douyin-downloader-main：运行中，当前任务：task-7"
    assert client.started == []
    assert client.stopped == []


def test_service_rejects_stop_when_downloader_is_idle():
    client = FakeClient({"gui_running": True, "busy": False, "ready": True})
    service = ControllerService(_config(), clients={"douyin-downloader-main": client})
    target = CommandRegistry().resolve("抖音：停止下载")

    response = service.handle_action(target, "stop-idle")

    assert response.accepted is False
    assert response.reason == "当前没有正在运行的任务，无需停止。"
    assert client.stopped == []


def test_service_deduplicates_repeated_request_id():
    client = FakeClient({"gui_running": True, "busy": False, "ready": True})
    service = ControllerService(_config(), clients={"douyin-downloader-main": client})
    target = CommandRegistry().resolve("抖音：开始下载")

    first = service.handle_action(target, "req-duplicate")
    second = service.handle_action(target, "req-duplicate")

    assert first.to_json() == second.to_json()
    assert client.started == ["req-duplicate"]


def test_service_deduplicates_concurrent_request_id():
    started = threading.Event()
    release = threading.Event()

    class BlockingClient(FakeClient):
        def start(self, _target, request_id):
            self.started.append(request_id)
            started.set()
            assert release.wait(timeout=2)
            return self.response

    client = BlockingClient({"gui_running": True, "busy": False, "ready": True})
    service = ControllerService(_config(), clients={"douyin-downloader-main": client})
    target = CommandRegistry().resolve("抖音：开始下载")
    responses = []
    threads = [
        threading.Thread(
            target=lambda: responses.append(service.handle_action(target, "req-race"))
        )
        for _ in range(2)
    ]

    for thread in threads:
        thread.start()
    assert started.wait(timeout=2)
    release.set()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert len(responses) == 2
    assert responses[0].to_json() == responses[1].to_json()
    assert client.started == ["req-race"]


def test_service_rejects_missing_target_process():
    client = FakeClient({"gui_running": False, "busy": False})
    service = ControllerService(_config(), clients={"bilibili-hiatus-analyzer": client})
    target = CommandRegistry().resolve("抖音：开始运行")

    response = service.handle_action(target, "req-1")

    assert response.accepted is False
    assert response.reason == "主程序未运行"


def test_service_routes_registered_plugin_without_hardcoded_target_branch():
    client = FakeClient({"gui_running": True, "busy": False, "ready": True})
    plugin = PluginSpec(
        plugin_id="video_tools",
        label="视频工具",
        base_url="http://127.0.0.1:9001",
        actions=(
            PluginAction("start", "视频处理", ("视频工具：开始处理",)),
            PluginAction("stop", "停止视频处理", ("视频工具：停止处理",)),
        ),
        required_ready_fields=("ready",),
    )
    config = BotConfig("app", "secret", "owner", control_token="token", plugins=(plugin,))
    service = ControllerService(config, clients={"video_tools": client})
    target = service.registry.resolve("视频工具：开始处理")

    response = service.handle_action(target, "video-1")

    assert response.accepted is True
    assert client.started == ["video-1"]


def test_service_status_text_lists_dynamically_registered_plugins():
    client = FakeClient({"gui_running": True, "busy": False, "ready": True})
    plugin = PluginSpec(
        plugin_id="video_tools",
        label="视频工具",
        base_url="http://127.0.0.1:9001",
        actions=(PluginAction("start", "视频处理", ("视频工具：开始处理",)),),
        required_ready_fields=("ready",),
    )
    config = BotConfig("app", "secret", "owner", control_token="token", plugins=(plugin,))
    service = ControllerService(config, clients={"video_tools": client})

    assert service.status_text() == "系统状态：\n视频工具：已启动，当前空闲"
