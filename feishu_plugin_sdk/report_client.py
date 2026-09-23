"""Standard-library client for posting plugin task reports."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)


class ReportClient:
    def __init__(
        self,
        controller_url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = 3.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.controller_url = (
            controller_url
            if controller_url is not None
            else os.environ.get("FEISHU_CONTROLLER_REPORT_URL", "")
        ).rstrip("/")
        self.token = token if token is not None else os.environ.get("FEISHU_CONTROL_TOKEN", "")
        self.timeout = max(float(timeout), 0.1)
        self.opener = opener

    def post(self, report: dict[str, Any]) -> bool:
        if not self.controller_url or not self.token:
            LOGGER.warning("task report is not configured")
            return False
        body = json.dumps(report, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.controller_url + "/api/v1/task-reports",
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                status = response.getcode() if hasattr(response, "getcode") else 200
                response.read()
            return 200 <= int(status) < 300
        except Exception as error:
            LOGGER.warning("task report submission failed: %s", error)
            return False
