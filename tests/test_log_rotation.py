from pathlib import Path

from log_rotation import BACKUP_COUNT, MAX_LOG_BYTES, RotatingTextStream


def test_rotating_stream_keeps_only_the_configured_number_of_backups(tmp_path):
    log_path = tmp_path / "controller.log"
    stream = RotatingTextStream(log_path, max_bytes=4, backup_count=2)

    stream.write("one\n")
    stream.write("two\n")
    stream.write("tri\n")
    stream.close()

    assert log_path.read_text(encoding="utf-8") == "tri\n"
    assert log_path.with_name("controller.log.1").read_text(encoding="utf-8") == "two\n"
    assert log_path.with_name("controller.log.2").read_text(encoding="utf-8") == "one\n"
    assert not log_path.with_name("controller.log.3").exists()


def test_rotating_stream_removes_backups_beyond_the_retention_limit(tmp_path):
    log_path = tmp_path / "controller.log"
    log_path.with_name("controller.log.3").write_text("stale", encoding="utf-8")
    stream = RotatingTextStream(log_path, max_bytes=4, backup_count=2)

    stream.write("one\n")
    stream.write("two\n")
    stream.close()

    assert not log_path.with_name("controller.log.3").exists()


def test_rotating_stream_removes_backups_when_retention_is_zero(tmp_path):
    log_path = tmp_path / "controller.log"
    log_path.with_name("controller.log.1").write_text("stale", encoding="utf-8")
    stream = RotatingTextStream(log_path, max_bytes=4, backup_count=0)

    stream.write("one\n")
    stream.write("two\n")
    stream.close()

    assert not log_path.with_name("controller.log.1").exists()


def test_rotating_stream_preserves_utf8_characters_when_splitting_writes(tmp_path):
    log_path = tmp_path / "controller.log"
    stream = RotatingTextStream(log_path, max_bytes=9, backup_count=2)

    stream.write("中文")
    stream.flush()
    stream.write("日志")
    stream.close()

    archived = log_path.with_name("controller.log.1").read_text(encoding="utf-8")
    active = log_path.read_text(encoding="utf-8")
    assert archived + active == "中文日志"


def test_default_rotation_policy_is_bounded():
    assert MAX_LOG_BYTES == 5 * 1024 * 1024
    assert BACKUP_COUNT == 5


def test_controller_launchers_use_rotating_log_runner():
    root = Path(__file__).parents[1]
    background = (root / "start_feishu_bot_background.bat").read_text(encoding="ascii")
    stack = (root / "start_feishu_stack.ps1").read_text(encoding="utf-8")

    assert "run_feishu_bot.py" in background
    assert "--stdout-log" in background
    assert "--stderr-log" in background
    assert ">>" not in background
    assert "run_feishu_bot.py" in stack
    assert "--stdout-log" in stack
    assert "--stderr-log" in stack
    assert "-RedirectStandardOutput" not in stack
    assert "-RedirectStandardError" not in stack

    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "*.log.*" in gitignore
