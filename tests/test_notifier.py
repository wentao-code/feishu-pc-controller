from notifier import Notifier, format_report_message
from task_protocol import TaskReport


def test_report_message_contains_summary_metrics():
    report = TaskReport.from_json(
        {
            "event_id": "event-1",
            "task_id": "task-1",
            "source": "douyin-downloader-main",
            "task_type": "douyin_download",
            "status": "partial",
            "elapsed_seconds": 61,
            "metrics": {"success": 8, "failed": 2, "skipped": 3},
        }
    )

    message = format_report_message(report)

    assert "抖音视频下载" in message
    assert "成功 8" in message
    assert "失败 2" in message
    assert "跳过 3" in message
    assert "耗时 00:01:01" in message


def test_notifier_retries_but_does_not_raise_when_sender_fails():
    attempts = []

    def sender(_message):
        attempts.append(True)
        raise RuntimeError("feishu unavailable")

    report = TaskReport.from_json(
        {
            "event_id": "event-1",
            "task_id": "task-1",
            "source": "bilibili-hiatus-analyzer",
            "task_type": "douyin_fetch",
            "status": "failed",
            "error": "目标程序异常",
        }
    )

    Notifier(sender, retry_delay=0).notify_report(report)

    assert len(attempts) == 3
