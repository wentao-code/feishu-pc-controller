import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import feishu_bot
from feishu_bot import (
    BotConfig,
    PluginEndpoint,
    command_for_message,
    command_help_text,
    discover_plugins,
    load_plugin_endpoints,
    load_config,
    on_message_receive,
    send_startup_notification,
)
from plugin_registry import PluginAction, PluginRegistry, PluginSpec
from task_protocol import CommandResponse


def test_load_config_reads_feishu_values_from_environment():
    env = {
        "FEISHU_APP_ID": "cli_test_app",
        "FEISHU_APP_SECRET": "test_secret",
        "FEISHU_OWNER_OPEN_ID": "ou_test_owner",
        "FEISHU_CONTROL_TOKEN": "control_token",
        "FEISHU_BILIBILI_HIATUS_ANALYZER_URL": "http://127.0.0.1:18761",
        "FEISHU_DOUYIN_DOWNLOADER_MAIN_URL": "http://127.0.0.1:18762",
    }

    config = load_config(env)

    assert config == BotConfig(
        app_id="cli_test_app",
        app_secret="test_secret",
        owner_open_id="ou_test_owner",
        control_token="control_token",
        bilibili_hiatus_analyzer_url="http://127.0.0.1:18761",
        douyin_downloader_main_url="http://127.0.0.1:18762",
    )


def test_load_config_ignores_removed_legacy_project_url_keys():
    config = load_config({
        "FEISHU_APP_ID": "cli_test_app",
        "FEISHU_APP_SECRET": "test_secret",
        "FEISHU_OWNER_OPEN_ID": "ou_test_owner",
        "FEISHU_CONTROL_TOKEN": "control_token",
        "FEISHU_MAIN_ANALYZER_URL": "http://127.0.0.1:9871",
        "FEISHU_DOUYIN_DOWNLOADER_URL": "http://127.0.0.1:9872",
    })

    assert config.bilibili_hiatus_analyzer_url == "http://127.0.0.1:8761"
    assert config.douyin_downloader_main_url == "http://127.0.0.1:8762"
    assert [plugin.plugin_id for plugin in feishu_bot.builtin_plugin_specs()] == [
        "bilibili-hiatus-analyzer",
        "douyin-downloader-main",
    ]


def test_load_config_reports_missing_required_values():
    with pytest.raises(ValueError, match="FEISHU_APP_SECRET"):
        load_config({
            "FEISHU_APP_ID": "cli_test_app",
            "FEISHU_OWNER_OPEN_ID": "ou_test_owner",
        })


def test_load_config_requires_control_token_for_remote_control():
    with pytest.raises(ValueError, match="FEISHU_CONTROL_TOKEN"):
        load_config({
            "FEISHU_APP_ID": "cli_test_app",
            "FEISHU_APP_SECRET": "test_secret",
            "FEISHU_OWNER_OPEN_ID": "ou_test_owner",
        })


def test_load_config_reads_dynamic_plugin_registry_from_json():
    config = load_config({
        "FEISHU_APP_ID": "cli_test_app",
        "FEISHU_APP_SECRET": "test_secret",
        "FEISHU_OWNER_OPEN_ID": "ou_test_owner",
        "FEISHU_CONTROL_TOKEN": "control_token",
        "FEISHU_PLUGINS_JSON": (
            '[{"id":"video_tools","label":"视频工具",'
            '"url":"http://127.0.0.1:9001",'
            '"actions":[{"name":"start","label":"视频处理",'
            '"aliases":["视频工具：开始处理"]}],'
            '"required_ready_fields":["ready"]}]'
        ),
    })

    assert [plugin.plugin_id for plugin in config.plugins] == ["video_tools"]
    assert config.plugins[0].required_ready_fields == ("ready",)
    assert config.plugins[0].actions[0].aliases == ("视频工具：开始处理",)


def test_load_config_rejects_invalid_dynamic_plugin_json():
    with pytest.raises(ValueError, match="FEISHU_PLUGINS_JSON"):
        load_config({
            "FEISHU_APP_ID": "cli_test_app",
            "FEISHU_APP_SECRET": "test_secret",
            "FEISHU_OWNER_OPEN_ID": "ou_test_owner",
            "FEISHU_CONTROL_TOKEN": "control_token",
            "FEISHU_PLUGINS_JSON": "not-json",
        })


def test_load_plugin_endpoints_parses_policy_overrides():
    endpoints = load_plugin_endpoints(
        '[{"id":"video_tools","url":"http://127.0.0.1:9001",'
        '"required_ready_fields":["ready"],'
        '"required_status_values":{"mode":["safe"]},'
        '"action_namespace":"video.tools"}]'
    )

    assert endpoints == (
        PluginEndpoint(
            plugin_id="video_tools",
            base_url="http://127.0.0.1:9001",
            required_ready_fields=("ready",),
            required_status_values={"mode": ("safe",)},
            action_namespace="video.tools",
        ),
    )


def test_plugin_endpoint_requires_ready_by_default():
    endpoint = load_plugin_endpoints(
        '[{"id":"video_tools","url":"http://127.0.0.1:9001"}]'
    )[0]

    assert endpoint.required_ready_fields == ("ready",)


def test_load_plugin_endpoints_rejects_missing_identity_or_duplicate_ids():
    with pytest.raises(ValueError, match="plugin endpoint id"):
        load_plugin_endpoints('[{"url":"http://127.0.0.1:9001"}]')

    with pytest.raises(ValueError, match="plugin endpoint url"):
        load_plugin_endpoints('[{"id":"video_tools"}]')

    with pytest.raises(ValueError, match="duplicate plugin endpoint"):
        load_plugin_endpoints(
            '[{"id":"video_tools","url":"http://127.0.0.1:9001"},'
            '{"id":"video_tools","url":"http://127.0.0.1:9002"}]'
        )

    with pytest.raises(ValueError, match="loopback"):
        load_plugin_endpoints('[{"id":"remote","url":"http://example.com:9001"}]')


def test_discover_plugins_isolates_offline_endpoint(monkeypatch):
    good_manifest = feishu_bot.PluginManifest(
        plugin_id="healthy_plugin",
        label="健康插件",
        version="1.0.0",
        actions=({"name": "start", "label": "开始", "aliases": ["健康：开始"]},),
    )

    class FakeManifestClient:
        def __init__(self, base_url, token, *, timeout):
            self.base_url = base_url

        def fetch(self):
            if self.base_url.endswith("9002"):
                raise feishu_bot.ManifestClientError("连接失败")
            return good_manifest

    monkeypatch.setattr(feishu_bot, "ManifestClient", FakeManifestClient)
    endpoints = (
        PluginEndpoint("healthy_plugin", "http://127.0.0.1:9001"),
        PluginEndpoint("offline_plugin", "http://127.0.0.1:9002"),
    )

    plugins = discover_plugins(endpoints, "secret", timeout=1)

    assert [plugin.plugin_id for plugin in plugins] == ["healthy_plugin", "offline_plugin"]
    assert plugins[1].actions[0].name == "status"


def test_discover_unbound_manifest_exposes_clear_control_bound_refusal(monkeypatch):
    manifest = feishu_bot.PluginManifest(
        plugin_id="scaffold_plugin",
        label="框架插件",
        version="1.0.0",
        actions=({"name": "start", "label": "开始", "aliases": ["框架：开始"]},),
        integration={"bound": False, "message": "框架尚未绑定业务入口"},
    )

    class FakeManifestClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def fetch(self):
            return manifest

    monkeypatch.setattr(feishu_bot, "ManifestClient", FakeManifestClient)

    plugin = feishu_bot.discover_plugins(
        (PluginEndpoint("scaffold_plugin", "http://127.0.0.1:9001"),),
        "secret",
        timeout=1,
    )[0]

    assert plugin.required_status_values["control_bound"] == (True,)
    assert plugin.refusal_messages["control_bound"] == "框架尚未绑定业务入口"
    assert plugin.status_messages["control_bound"] == "框架尚未绑定业务入口"


def test_load_config_adds_discovered_plugins_without_dropping_legacy_plugins(monkeypatch):
    captured = []

    def fake_discover(endpoints, token, *, timeout):
        captured.append((endpoints, token, timeout))
        return ()

    monkeypatch.setattr(feishu_bot, "discover_plugins", fake_discover)
    config = load_config(
        {
            "FEISHU_APP_ID": "cli_test_app",
            "FEISHU_APP_SECRET": "test_secret",
            "FEISHU_OWNER_OPEN_ID": "ou_test_owner",
            "FEISHU_CONTROL_TOKEN": "control_token",
            "FEISHU_PLUGIN_ENDPOINTS_JSON": (
                '[{"id":"offline_plugin","url":"http://127.0.0.1:9002"}]'
            ),
            "FEISHU_PLUGINS_JSON": (
                '[{"id":"static_plugin","label":"静态插件",'
                '"url":"http://127.0.0.1:9003",'
                '"actions":[{"name":"start","label":"开始",'
                '"aliases":["静态：开始"]}]}]'
            ),
        }
    )

    assert len(captured) == 1
    assert captured[0][0][0].plugin_id == "offline_plugin"
    assert [plugin.plugin_id for plugin in config.plugins] == [
        "bilibili-hiatus-analyzer",
        "douyin-downloader-main",
    ]
    assert config.plugins_configured is True


def test_owner_commands_are_normalized():
    assert command_for_message("  STATUS ") == "status"
    assert command_for_message("关机") == "shutdown"
    assert command_for_message("关闭电脑") == "shutdown"
    assert command_for_message("取消关机") == "cancel_shutdown"
    assert command_for_message("cancel") == "cancel_shutdown"
    assert command_for_message("指令集合") == "help"
    assert command_for_message("帮助") == "help"
    assert command_for_message("help") == "help"
    assert command_for_message("抖音：停止运行") == "douyin_fetch_stop"
    assert command_for_message("douyin download stop") == "echo"
    assert command_for_message("201") == "douyin_download_start"
    assert command_for_message("未知指令") == "echo"


def test_global_numeric_commands_are_supported():
    assert command_for_message("001") == "shutdown"
    assert command_for_message("002") == "cancel_shutdown"
    assert command_for_message("003") == "status"
    assert command_for_message("004") == "help"


def test_command_help_lists_commands_and_expected_replies():
    help_text = command_help_text()

    assert "状态 / status" in help_text
    assert "查看所有已接入系统的运行状态" in help_text
    assert "关机 / shutdown / 关闭电脑" in help_text
    assert "15秒后关机" in help_text
    assert "取消关机 / cancel" in help_text
    assert "已取消关机任务" in help_text
    assert "抖音：停止运行" in help_text
    assert "抖音：停止下载" in help_text
    assert "001. 关机" in help_text
    assert "002. 取消关机" in help_text
    assert "003. 状态" in help_text
    assert "004. 指令集合" in help_text
    assert "101." in help_text
    assert "103." in help_text
    assert "201." in help_text
    assert "203." in help_text
    assert "bilibili-hiatus-analyzer" in help_text
    assert "douyin-downloader-main" in help_text


def test_command_help_lists_dynamically_registered_plugin_commands():
    registry = feishu_bot.CommandRegistry(
        PluginRegistry(
            [
                PluginSpec(
                    plugin_id="video_tools",
                    label="视频工具",
                    base_url="http://127.0.0.1:9001",
                    actions=(
                        PluginAction("start", "视频处理", ("视频工具：开始处理",)),
                    ),
                )
            ]
        )
    )

    assert "视频工具：开始处理" in feishu_bot.command_help_text(registry)


def test_stop_command_replies_immediately_without_faking_completion(monkeypatch):
    config = BotConfig("app", "secret", "ou-owner", control_token="token")
    sent = []
    monkeypatch.setattr(
        feishu_bot,
        "send_message_to_owner",
        lambda text, config, client: sent.append(text),
    )

    class FakeService:
        registry = feishu_bot.CommandRegistry()

        def handle_action(self, target, request_id):
            assert target.target_action == "stop"
            return CommandResponse(
                request_id=request_id,
                accepted=True,
                status="accepted",
                message="已提交停止请求",
                task_id="run-1",
            )

    data = SimpleNamespace(
        event_id="stop-event",
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type="text",
                content=json.dumps({"text": "抖音：停止下载"}),
            ),
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou-owner")),
        ),
    )

    on_message_receive(data, config, client=object(), controller_service=FakeService())

    assert sent == ["停止请求已提交，当前处理完成后会安全停止。"]


def test_dynamic_plugin_command_is_dispatched_without_controller_branch(monkeypatch):
    config = BotConfig("app", "secret", "ou-owner", control_token="token")
    sent = []
    monkeypatch.setattr(
        feishu_bot,
        "send_message_to_owner",
        lambda text, config, client: sent.append(text),
    )
    registry = feishu_bot.CommandRegistry(
        PluginRegistry(
            [
                PluginSpec(
                    plugin_id="video_tools",
                    label="视频工具",
                    base_url="http://127.0.0.1:9001",
                    actions=(PluginAction("start", "视频处理", ("视频工具：开始处理",)),),
                )
            ]
        )
    )

    class FakeService:
        def __init__(self):
            self.registry = registry
            self.received = []

        def handle_action(self, target, request_id):
            self.received.append((target.action, request_id))
            return CommandResponse(
                request_id=request_id,
                accepted=True,
                status="accepted",
                task_id="video-1",
            )

    service = FakeService()
    data = SimpleNamespace(
        event_id="video-event",
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type="text",
                content=json.dumps({"text": "视频工具：开始处理"}),
            ),
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou-owner")),
        ),
    )

    on_message_receive(data, config, client=object(), controller_service=service)

    assert service.received == [("video_tools.start", "video-event")]
    assert sent == ["已接受视频处理，正在按当前配置启动。任务 ID：video-1"]


def test_numbered_plugin_command_dispatches_to_registered_project(monkeypatch):
    config = BotConfig("app", "secret", "ou-owner", control_token="token")
    sent = []
    monkeypatch.setattr(
        feishu_bot,
        "send_message_to_owner",
        lambda text, config, client: sent.append(text),
    )
    registry = feishu_bot.CommandRegistry(
        PluginRegistry(
            [
                PluginSpec(
                    plugin_id="local_video_renamer",
                    label="Local Video Renamer",
                    base_url="http://127.0.0.1:9003",
                    actions=(PluginAction("start", "开始重命名", ("重命名：开始",)),),
                )
            ]
        )
    )

    class FakeService:
        def __init__(self):
            self.registry = registry
            self.received = []

        def handle_action(self, target, request_id):
            self.received.append((target.target, target.target_action, request_id))
            return CommandResponse(
                request_id=request_id,
                accepted=True,
                status="accepted",
                task_id="rename-1",
            )

    service = FakeService()
    data = SimpleNamespace(
        event_id="renamer-code-event",
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type="text",
                content=json.dumps({"text": "301"}),
            ),
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou-owner")),
        ),
    )

    on_message_receive(data, config, client=object(), controller_service=service)

    assert service.received == [("local_video_renamer", "start", "renamer-code-event")]
    assert sent == ["已接受开始重命名，正在按当前配置启动。任务 ID：rename-1"]


def test_dynamic_plugin_status_command_replies_with_status_without_dispatch(monkeypatch):
    config = BotConfig("app", "secret", "ou-owner", control_token="token")
    sent = []
    monkeypatch.setattr(
        feishu_bot,
        "send_message_to_owner",
        lambda text, config, client: sent.append(text),
    )
    registry = feishu_bot.CommandRegistry(
        PluginRegistry(
            [
                PluginSpec(
                    plugin_id="video_tools",
                    label="视频工具",
                    base_url="http://127.0.0.1:9001",
                    actions=(
                        PluginAction("status", "查看视频工具状态", ("视频工具：状态",)),
                    ),
                )
            ]
        )
    )

    class FakeService:
        def __init__(self):
            self.registry = registry
            self.received = []

        def handle_action(self, target, request_id):
            self.received.append((target.action, request_id))
            return CommandResponse(
                request_id=request_id,
                accepted=True,
                status="accepted",
                message="视频工具：就绪",
            )

    service = FakeService()
    data = SimpleNamespace(
        event_id="video-status-event",
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type="text",
                content=json.dumps({"text": "视频工具：状态"}),
            ),
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou-owner")),
        ),
    )

    on_message_receive(data, config, client=object(), controller_service=service)

    assert service.received == [("video_tools.status", "video-status-event")]
    assert sent == ["视频工具：就绪"]


def test_plugin_status_includes_active_task_title_and_waiting_count():
    plugin = PluginSpec(
        plugin_id="video_tools",
        label="视频工具",
        base_url="http://127.0.0.1:9001",
        actions=(PluginAction("status", "状态", ("视频工具：状态",)),),
    )

    message = feishu_bot.ControllerService._format_plugin_status(
        plugin,
        {
            "gui_running": True,
            "busy": True,
            "task_id": "trace-1",
            "task_title": "扫描本地视频",
            "queue_depth": 2,
        },
    )

    assert message == "视频工具：运行中，当前任务：扫描本地视频，另有 2 项排队"


def test_plugin_status_does_not_treat_unpublished_queue_as_idle():
    plugin = PluginSpec(
        plugin_id="video_tools",
        label="视频工具",
        base_url="http://127.0.0.1:9001",
        actions=(PluginAction("status", "状态", ("视频工具：状态",)),),
    )

    message = feishu_bot.ControllerService._format_plugin_status(
        plugin,
        {"gui_running": True, "busy": False, "task_status_known": False},
    )

    assert message == "视频工具：任务状态未知，尚未接入 GUI 任务队列"


def test_plugin_status_reports_waiting_tasks_when_none_are_active():
    plugin = PluginSpec(
        plugin_id="video_tools",
        label="视频工具",
        base_url="http://127.0.0.1:9001",
        actions=(PluginAction("status", "状态", ("视频工具：状态",)),),
    )

    message = feishu_bot.ControllerService._format_plugin_status(
        plugin,
        {"gui_running": True, "busy": False, "task_status_known": True, "queue_depth": 1},
    )

    assert message == "视频工具：当前无任务执行，另有 1 项等待处理"


def test_plugin_status_reports_idle_even_when_start_stop_callbacks_are_unbound():
    plugin = PluginSpec(
        plugin_id="video_tools",
        label="视频工具",
        base_url="http://127.0.0.1:9001",
        actions=(PluginAction("status", "状态", ("视频工具：状态",)),),
        required_status_values={"control_bound": (True,)},
        status_messages={"control_bound": "控制回调未绑定"},
    )

    message = feishu_bot.ControllerService._format_plugin_status(
        plugin,
        {
            "gui_running": True,
            "task_status_known": True,
            "busy": False,
            "control_bound": False,
        },
    )

    assert message == "视频工具：已启动，当前空闲"


def test_unknown_message_returns_full_help_text_without_dispatching(monkeypatch):
    config = BotConfig("app", "secret", "ou-owner", control_token="token")
    sent = []
    monkeypatch.setattr(
        feishu_bot,
        "send_message_to_owner",
        lambda text, config, client: sent.append(text),
    )

    class FakeService:
        registry = feishu_bot.CommandRegistry()

        def handle_action(self, _target, _request_id):
            raise AssertionError("unknown messages must not be dispatched")

    text = "分布广泛的好吧"
    data = SimpleNamespace(
        event_id="unknown-event",
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type="text",
                content=json.dumps({"text": text}),
            ),
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou-owner")),
        ),
    )

    on_message_receive(data, config, client=object(), controller_service=FakeService())

    assert len(sent) == 1
    assert "可用指令：" in sent[0]
    assert "抖音：开始运行" in sent[0]
    assert "抖音：停止运行" in sent[0]
    assert "抖音：开始下载" in sent[0]
    assert "抖音：停止下载" in sent[0]
    assert "未知指令" not in sent[0]


def test_pending_shutdown_can_be_cancelled(monkeypatch):
    class FakeTimer:
        instance = None

        def __init__(self, interval, function):
            self.interval = interval
            self.function = function
            self.cancelled = False
            FakeTimer.instance = self

        def start(self):
            return None

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(feishu_bot.threading, "Timer", FakeTimer)

    assert feishu_bot.cancel_shutdown() is False
    feishu_bot.handle_shutdown()

    assert FakeTimer.instance.interval == 15
    assert feishu_bot.cancel_shutdown() is True
    assert FakeTimer.instance.cancelled is True
    assert feishu_bot.cancel_shutdown() is False


def test_startup_notification_sends_expected_message(monkeypatch):
    config = BotConfig("cli_test_app", "test_secret", "ou_test_owner")
    sent = []

    monkeypatch.setattr(
        feishu_bot,
        "send_message_to_owner",
        lambda text, config, client: sent.append((text, config, client)),
    )
    client = object()

    send_startup_notification(config, client)

    assert sent == [("通知助手开始工作", config, client)]


def test_windows_launcher_uses_cmd_compatible_format():
    launcher = Path(__file__).parents[1] / "start_feishu_bot.bat"
    content = launcher.read_bytes()

    assert b"\r\n" in content
    assert b"\n" not in content.replace(b"\r\n", b"")
    assert b'start_feishu_stack.bat' in content


def test_background_launcher_redirects_output_to_a_log():
    launcher = Path(__file__).parents[1] / "start_feishu_bot_background.bat"
    content = launcher.read_bytes()

    assert b"\r\n" in content
    assert b"\n" not in content.replace(b"\r\n", b"")
    assert b'-u "%~dp0run_feishu_bot.py"' in content
    assert b'--stdout-log "%~dp0feishu_bot.log"' in content
    assert b'--stderr-log "%~dp0feishu_bot.log"' in content
    assert b'>>' not in content


def test_autostart_scripts_register_and_remove_the_same_task():
    root = Path(__file__).parents[1]
    install_script = (root / "install_autostart.ps1").read_text(encoding="utf-8")
    uninstall_script = (root / "uninstall_autostart.ps1").read_text(encoding="utf-8")

    assert 'Feishu PC Controller' in install_script
    assert "Register-ScheduledTask" in install_script
    assert "-AtLogOn" in install_script
    assert "-RestartCount" in install_script
    assert "python-path.txt" in install_script
    assert "start_feishu_stack.bat" in install_script
    assert 'Feishu PC Controller' in uninstall_script
    assert "Unregister-ScheduledTask" in uninstall_script


def test_background_launcher_prefers_installed_python_path():
    launcher = (Path(__file__).parents[1] / "start_feishu_bot_background.bat").read_text(
        encoding="ascii"
    )

    assert "runtime\\python-path.txt" in launcher


def test_unified_stack_launcher_starts_controller_without_launching_targets():
    root = Path(__file__).parents[1]
    launcher = (root / "start_feishu_stack.bat").read_bytes()
    script = (root / "start_feishu_stack.ps1").read_text(encoding="utf-8")

    assert b"\r\n" in launcher
    assert b"powershell.exe" in launcher.lower()
    assert "run_feishu_bot.py" in script
    assert "-WindowStyle Hidden" in script
    assert "--stdout-log" in script
    assert "--stderr-log" in script
    assert "Target applications are monitored only" in script
    assert "start_gui.bat" not in script
    assert "quark_manager.control_server" not in script
