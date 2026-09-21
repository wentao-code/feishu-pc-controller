from datetime import datetime, timezone

import pytest

from task_protocol import (
    CommandRequest,
    CommandResponse,
    TaskReport,
)


def test_command_request_round_trips_supported_action():
    request = CommandRequest.from_json(
        {
            "request_id": "req-1",
            "action": "douyin.fetch.start",
            "source": "feishu",
        }
    )

    assert request.to_json() == {
        "request_id": "req-1",
        "action": "douyin.fetch.start",
        "source": "feishu",
    }


def test_command_request_requires_id_and_known_action():
    with pytest.raises(ValueError, match="request_id"):
        CommandRequest.from_json({"action": "douyin.fetch.start"})

    with pytest.raises(ValueError, match="action"):
        CommandRequest.from_json({"request_id": "req-1", "action": "unknown"})


def test_command_response_preserves_rejection_reason():
    response = CommandResponse(
        request_id="req-1",
        accepted=False,
        status="rejected",
        reason="当前配置未锁定",
    )

    assert response.to_json()["reason"] == "当前配置未锁定"
    assert response.to_json()["accepted"] is False


def test_task_report_normalizes_timestamps_and_metrics():
    report = TaskReport.from_json(
        {
            "event_id": "event-1",
            "task_id": "task-1",
            "source": "main_analyzer",
            "task_type": "douyin_fetch",
            "status": "succeeded",
            "started_at": "2026-09-21T04:00:00+00:00",
            "finished_at": "2026-09-21T04:01:00+00:00",
            "elapsed_seconds": 60,
            "metrics": {"success": 2, "failed": 0, "skipped": 1},
        }
    )

    assert report.started_at == datetime(2026, 9, 21, 4, tzinfo=timezone.utc)
    assert report.metrics == {"success": 2, "failed": 0, "skipped": 1}


def test_task_report_rejects_unknown_terminal_status():
    with pytest.raises(ValueError, match="status"):
        TaskReport.from_json(
            {
                "event_id": "event-1",
                "task_id": "task-1",
                "source": "main_analyzer",
                "task_type": "douyin_fetch",
                "status": "finished",
            }
        )
