from command_registry import CommandRegistry, normalize_command


def test_normalize_command_accepts_chinese_colon_and_spacing():
    assert normalize_command("  抖音：开始运行 ") == "douyin.fetch.start"
    assert normalize_command("抖音: 开始下载") == "douyin.download.start"


def test_registry_exposes_only_first_release_actions_and_status():
    registry = CommandRegistry()

    fetch = registry.resolve("抖音：开始运行")
    download = registry.resolve("抖音：开始下载")
    status = registry.resolve("状态")

    assert fetch.action == "douyin.fetch.start"
    assert fetch.target == "main_analyzer"
    assert fetch.target_action == "start"
    assert download.target == "douyin_downloader"
    assert status.action == "system.status"
    assert registry.resolve("抖音：删除全部文件") is None


def test_registry_resolves_stop_commands_and_aliases():
    registry = CommandRegistry()

    fetch_stop = registry.resolve("抖音：停止运行")
    download_stop = registry.resolve("douyin download stop")

    assert fetch_stop.action == "douyin.fetch.stop"
    assert fetch_stop.target == "main_analyzer"
    assert fetch_stop.target_action == "stop"
    assert download_stop.action == "douyin.download.stop"
    assert download_stop.target == "douyin_downloader"
    assert download_stop.target_action == "stop"


def test_registry_resolves_per_plugin_status_commands():
    registry = CommandRegistry()
    fetch_status = registry.resolve("抖音：状态")
    download_status = registry.resolve("抖音下载：状态")

    assert fetch_status.action == "douyin.fetch.status"
    assert fetch_status.target == "main_analyzer"
    assert fetch_status.target_action == "status"
    assert download_status.action == "douyin.download.status"
    assert download_status.target == "douyin_downloader"
    assert download_status.target_action == "status"
