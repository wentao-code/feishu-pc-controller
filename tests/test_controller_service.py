from command_registry import CommandRegistry
from feishu_bot import BotConfig, ControllerService, command_for_message
from task_protocol import CommandResponse


class FakeClient:
    def __init__(self, status, response=None):
        self.status = status
        self.response = response or CommandResponse("req-1", True, "accepted", task_id="task-1")
        self.started = []

    def get_status(self, _target):
        return dict(self.status)

    def start(self, _target, request_id):
        self.started.append(request_id)
        return self.response


def _config():
    return BotConfig("app", "secret", "owner", control_token="token")


def test_feishu_start_commands_map_to_stable_commands():
    assert command_for_message("抖音：开始运行") == "douyin_fetch_start"
    assert command_for_message("抖音：开始下载") == "douyin_download_start"


def test_service_rejects_analyzer_when_configuration_is_unlocked():
    client = FakeClient({"gui_running": True, "busy": False, "config_locked": False})
    service = ControllerService(_config(), clients={"main_analyzer": client})
    target = CommandRegistry().resolve("抖音：开始运行")

    response = service.handle_action(target, "req-1")

    assert response.accepted is False
    assert response.reason == "当前配置未锁定，请先在主程序中锁定配置"
    assert client.started == []


def test_service_starts_ready_downloader_once():
    client = FakeClient({"gui_running": True, "busy": False, "ready": True})
    service = ControllerService(_config(), clients={"douyin_downloader": client})
    target = CommandRegistry().resolve("抖音：开始下载")

    response = service.handle_action(target, "req-1")

    assert response.accepted is True
    assert client.started == ["req-1"]


def test_service_rejects_missing_target_process():
    client = FakeClient({"gui_running": False, "busy": False})
    service = ControllerService(_config(), clients={"main_analyzer": client})
    target = CommandRegistry().resolve("抖音：开始运行")

    response = service.handle_action(target, "req-1")

    assert response.accepted is False
    assert response.reason == "主程序未运行"
