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
