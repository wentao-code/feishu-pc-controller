"""Shared JSON protocol for the Feishu control gateway and task clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


SUPPORTED_ACTIONS = frozenset(
    {
        "douyin.fetch.start",
        "douyin.download.start",
        "system.status",
    }
)
COMMAND_STATUSES = frozenset({"accepted", "rejected", "already_running"})
TERMINAL_STATUSES = frozenset({"succeeded", "partial", "failed", "cancelled"})


def _required_text(payload: Mapping[str, Any], name: str) -> str:
    value = str(payload.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _parse_timestamp(value: Any, name: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{name} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp_json(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class CommandRequest:
    request_id: str
    action: str
    source: str = "feishu"

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "CommandRequest":
        request_id = _required_text(payload, "request_id")
        action = _required_text(payload, "action")
        if action not in SUPPORTED_ACTIONS:
            raise ValueError(f"unsupported action: {action}")
        return cls(
            request_id=request_id,
            action=action,
            source=str(payload.get("source") or "feishu").strip() or "feishu",
        )

    def to_json(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "source": self.source,
        }


@dataclass(frozen=True)
class CommandResponse:
    request_id: str
    accepted: bool
    status: str
    message: str = ""
    reason: str | None = None
    task_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in COMMAND_STATUSES:
            raise ValueError(f"unsupported command status: {self.status}")

    def to_json(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "accepted": self.accepted,
            "status": self.status,
            "message": self.message,
            "reason": self.reason,
            "task_id": self.task_id,
        }


@dataclass(frozen=True)
class TaskReport:
    event_id: str
    task_id: str
    source: str
    task_type: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_seconds: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in TERMINAL_STATUSES:
            raise ValueError(f"unsupported report status: {self.status}")

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "TaskReport":
        metrics = payload.get("metrics") or {}
        details = payload.get("details") or {}
        if not isinstance(metrics, Mapping):
            raise ValueError("metrics must be an object")
        if not isinstance(details, Mapping):
            raise ValueError("details must be an object")
        status = _required_text(payload, "status")
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"unsupported report status: {status}")
        elapsed = payload.get("elapsed_seconds")
        try:
            elapsed_seconds = float(elapsed) if elapsed is not None else None
        except (TypeError, ValueError) as error:
            raise ValueError("elapsed_seconds must be numeric") from error
        return cls(
            event_id=_required_text(payload, "event_id"),
            task_id=_required_text(payload, "task_id"),
            source=_required_text(payload, "source"),
            task_type=_required_text(payload, "task_type"),
            status=status,
            started_at=_parse_timestamp(payload.get("started_at"), "started_at"),
            finished_at=_parse_timestamp(payload.get("finished_at"), "finished_at"),
            elapsed_seconds=elapsed_seconds,
            metrics=dict(metrics),
            details=dict(details),
            error=str(payload.get("error") or "") or None,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "source": self.source,
            "task_type": self.task_type,
            "status": self.status,
            "started_at": _timestamp_json(self.started_at),
            "finished_at": _timestamp_json(self.finished_at),
            "elapsed_seconds": self.elapsed_seconds,
            "metrics": dict(self.metrics),
            "details": dict(self.details),
            "error": self.error,
        }
