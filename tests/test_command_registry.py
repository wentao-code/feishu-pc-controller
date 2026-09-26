from command_registry import CommandRegistry, normalize_command
from plugin_registry import PluginAction, PluginRegistry, PluginSpec


def test_normalize_command_accepts_chinese_colon_and_spacing():
    assert normalize_command("  抖音：开始运行 ") == "douyin.fetch.start"
    assert normalize_command("抖音: 开始下载") == "douyin.download.start"


def test_registry_exposes_only_first_release_actions_and_status():
    registry = CommandRegistry()

    fetch = registry.resolve("抖音：开始运行")
    download = registry.resolve("抖音：开始下载")
    status = registry.resolve("状态")

    assert fetch.action == "douyin.fetch.start"
    assert fetch.target == "bilibili-hiatus-analyzer"
    assert fetch.target_action == "start"
    assert download.target == "douyin-downloader-main"
    assert status.action == "system.status"
    assert registry.resolve("抖音：删除全部文件") is None


def test_registry_resolves_stop_commands_and_aliases():
    registry = CommandRegistry()

    fetch_stop = registry.resolve("抖音：停止运行")
    download_stop = registry.resolve("抖音：停止下载")

    assert fetch_stop.action == "douyin.fetch.stop"
    assert fetch_stop.target == "bilibili-hiatus-analyzer"
    assert fetch_stop.target_action == "stop"
    assert download_stop.action == "douyin.download.stop"
    assert download_stop.target == "douyin-downloader-main"
    assert download_stop.target_action == "stop"


def test_registry_resolves_per_plugin_status_commands():
    registry = CommandRegistry()
    fetch_status = registry.resolve("抖音：状态")
    download_status = registry.resolve("抖音下载：状态")

    assert fetch_status.action == "douyin.fetch.status"
    assert fetch_status.target == "bilibili-hiatus-analyzer"
    assert fetch_status.target_action == "status"
    assert download_status.action == "douyin.download.status"
    assert download_status.target == "douyin-downloader-main"
    assert download_status.target_action == "status"


def test_registry_resolves_stable_numeric_plugin_commands():
    registry = CommandRegistry()

    expected = {
        "101": ("bilibili-hiatus-analyzer", "start"),
        "102": ("bilibili-hiatus-analyzer", "stop"),
        "103": ("bilibili-hiatus-analyzer", "status"),
        "201": ("douyin-downloader-main", "start"),
        "202": ("douyin-downloader-main", "stop"),
        "203": ("douyin-downloader-main", "status"),
    }

    for code, (plugin_id, action) in expected.items():
        resolved = registry.resolve(code)
        assert (resolved.target, resolved.target_action) == (plugin_id, action)

    assert registry.plugins.get("bilibili-hiatus-analyzer").label == "bilibili-hiatus-analyzer"
    assert registry.plugins.get("douyin-downloader-main").label == "douyin-downloader-main"


def test_registry_resolves_local_renamer_and_quark_codes_independent_of_order():
    plugins = PluginRegistry(
        [
            PluginSpec("quark_file_management", "夸克", "http://127.0.0.1:9004", tuple(
                PluginAction(action, action, (f"quark {action}",))
                for action in ("start", "stop", "status")
            )),
            PluginSpec("local_video_renamer", "重命名", "http://127.0.0.1:9003", tuple(
                PluginAction(action, action, (f"renamer {action}",))
                for action in ("start", "stop", "status")
            )),
        ]
    )
    registry = CommandRegistry(plugins)

    assert registry.resolve("301").target == "local_video_renamer"
    assert registry.resolve("302").target_action == "stop"
    assert registry.resolve("303").target_action == "status"
    assert registry.resolve("401").target == "quark_file_management"
    assert registry.resolve("402").target_action == "stop"
    assert registry.resolve("403").target_action == "status"


def test_registry_resolves_application_lifecycle_codes_and_named_commands():
    registry = CommandRegistry()
    expected = {
        "104": ("bilibili-hiatus-analyzer", "launch"),
        "105": ("bilibili-hiatus-analyzer", "close"),
        "204": ("douyin-downloader-main", "launch"),
        "205": ("douyin-downloader-main", "close"),
        "304": ("local_video_renamer", "launch"),
        "305": ("local_video_renamer", "close"),
        "404": ("quark_file_management", "launch"),
        "405": ("quark_file_management", "close"),
    }

    for code, (plugin_id, operation) in expected.items():
        resolved = registry.resolve(code)
        assert (resolved.target, resolved.target_action) == (plugin_id, operation)
        assert resolved.action == f"application.{operation}"

    assert registry.resolve("bilibili-hiatus-analyzer：启动项目").target_action == "launch"
    assert registry.resolve("Quark File Management：关闭项目").target_action == "close"


def test_canonical_project_names_replace_old_ids_and_english_command_aliases():
    registry = CommandRegistry()

    assert registry.resolve("bilibili-hiatus-analyzer start") is None
    assert registry.resolve("douyin-downloader-main stop") is None
    assert registry.resolve("douyinstart") is None
    assert registry.resolve("douyindownload") is None
    assert registry.resolve("main_analyzer status") is None
    assert registry.resolve("douyin_downloader status") is None
    assert registry.resolve("抖音：开始运行").target == "bilibili-hiatus-analyzer"
    assert registry.resolve("抖音：停止下载").target == "douyin-downloader-main"


def test_help_uses_category_codes_and_canonical_project_order():
    plugins = PluginRegistry(
        [
            PluginSpec("quark_file_management", "Quark", "http://127.0.0.1:9004", tuple(
                PluginAction(action, action, (f"quark {action}",))
                for action in ("status", "start", "stop")
            )),
            PluginSpec("local_video_renamer", "Renamer", "http://127.0.0.1:9003", tuple(
                PluginAction(action, action, (f"renamer {action}",))
                for action in ("status", "start", "stop")
            )),
        ]
    )

    help_text = CommandRegistry(plugins).help_text()
    numbered_lines = [line for line in help_text.splitlines() if line[:3].isdigit()]

    assert [line[:3] for line in numbered_lines] == [
        "104", "105", "204", "205",
        "301", "302", "303", "304", "305",
        "401", "402", "403", "404", "405",
    ]
    assert "301. renamer start" in help_text


def test_help_includes_application_lifecycle_codes_for_all_four_projects():
    lines = CommandRegistry().help_text().splitlines()

    assert [line[:3] for line in lines if line[:3].isdigit() and line[1:3] in {"04", "05"}] == [
        "104", "105", "204", "205", "304", "305", "404", "405"
    ]
    assert "104. bilibili-hiatus-analyzer：启动项目" in lines
    assert "405. Quark File Management：关闭项目" in lines
