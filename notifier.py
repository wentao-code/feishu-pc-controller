"""Format and deliver task summaries without coupling delivery to task execution."""

from __future__ import annotations

import logging
import time
from typing import Callable

from task_protocol import TaskReport


LOGGER = logging.getLogger(__name__)


def _elapsed_text(seconds: float | None) -> str:
    total = max(int(seconds or 0), 0)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_report_message(report: TaskReport) -> str:
    details = report.details
    if details.get("alert_type") == "douyin_login_invalid":
        aweme_id = str(details.get("aweme_id") or "").strip()
        if details.get("alert_phase") == "detected":
            lines = [
                "抖音登录状态失效，下载任务已自动停止。",
                "请在抖音浏览器中重新登录后再运行。",
            ]
            if aweme_id:
                lines.append(f"触发作品：{aweme_id}")
            return "\n".join(lines)

        metrics = report.metrics
        metrics_text = (
            f"成功 {metrics.get('success', 0)}，"
            f"失败 {metrics.get('failed', 0)}，"
            f"跳过 {metrics.get('skipped', 0)}"
        )
        lines = [
            "抖音登录状态失效，下载任务已停止。",
            f"最终统计：{metrics_text}",
            f"耗时 {_elapsed_text(report.elapsed_seconds)}",
            "请重新登录后再运行。",
        ]
        if aweme_id:
            lines.insert(1, f"触发作品：{aweme_id}")
        return "\n".join(lines)

    labels = {
        "douyin_fetch": "抖音抓取",
        "douyin_download": "抖音视频下载",
    }
    status_labels = {
        "succeeded": "已完成",
        "partial": "部分完成",
        "failed": "失败",
        "cancelled": "已取消",
    }
    metrics = report.metrics
    lines = [
        f"任务{labels.get(report.task_type, report.task_type)}：{status_labels[report.status]}",
        f"任务 ID：{report.task_id}",
        f"成功 {metrics.get('success', 0)}，失败 {metrics.get('failed', 0)}，跳过 {metrics.get('skipped', 0)}",
        f"耗时 {_elapsed_text(report.elapsed_seconds)}",
    ]
    if metrics.get("invalid") is not None:
        lines.append(f"失效 {metrics.get('invalid', 0)}")
    if report.error:
        lines.append(f"原因：{report.error}")
    return "\n".join(lines)


class Notifier:
    def __init__(
        self,
        sender: Callable[[str], None],
        *,
        max_attempts: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self.sender = sender
        self.max_attempts = max(int(max_attempts), 1)
        self.retry_delay = max(float(retry_delay), 0.0)

    def notify_report(self, report: TaskReport) -> None:
        message = format_report_message(report)
        for attempt in range(1, self.max_attempts + 1):
            try:
                self.sender(message)
                return
            except Exception as error:
                LOGGER.warning("Feishu notification failed on attempt %s: %s", attempt, error)
                if attempt < self.max_attempts and self.retry_delay:
                    time.sleep(self.retry_delay)
