"""Common manifest model for Feishu-controlled local plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


_SUPPORTED_ACTIONS = frozenset({"start", "stop", "status"})
_DEFAULT_PROTOCOL = {
    "manifest": "/api/v1/manifest",
    "status": "/api/v1/status",
    "commands": "/api/v1/commands",
}
_DEFAULT_REPORTING = {
    "client": "feishu_plugin_sdk.ReportClient",
    "controller_path": "/api/v1/task-reports",
}


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


@dataclass(frozen=True)
class PluginManifest:
    """Validated, JSON-serializable capability description for one plugin."""

    plugin_id: str
    label: str
    version: str
    actions: tuple[Mapping[str, Any], ...]
    schema_version: str = "1.0"
    protocol: Mapping[str, str] = field(default_factory=lambda: dict(_DEFAULT_PROTOCOL))
    reporting: Mapping[str, str] = field(default_factory=lambda: dict(_DEFAULT_REPORTING))
    integration: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _required_text(self.schema_version, "schema_version"))
        object.__setattr__(self, "plugin_id", _required_text(self.plugin_id, "plugin_id"))
        object.__setattr__(self, "label", _required_text(self.label, "label"))
        object.__setattr__(self, "version", _required_text(self.version, "version"))

        normalized_actions: list[dict[str, Any]] = []
        action_names: set[str] = set()
        for action in self.actions:
            if not isinstance(action, Mapping):
                raise ValueError("manifest action must be an object")
            name = _required_text(action.get("name"), "action name")
            if name not in _SUPPORTED_ACTIONS:
                raise ValueError(f"unsupported action: {name}")
            if name in action_names:
                raise ValueError(f"duplicate action: {name}")
            label = _required_text(action.get("label"), "action label")
            aliases = action.get("aliases") or ()
            if isinstance(aliases, str) or not isinstance(aliases, (list, tuple)):
                raise ValueError(f"aliases must be an array for action: {name}")
            normalized_aliases = tuple(_required_text(alias, "action alias") for alias in aliases)
            if not normalized_aliases:
                raise ValueError(f"aliases are required for action: {name}")
            action_names.add(name)
            normalized_actions.append(
                {"name": name, "label": label, "aliases": list(normalized_aliases)}
            )
        if not normalized_actions:
            raise ValueError("manifest must declare at least one action")

        protocol = dict(_DEFAULT_PROTOCOL)
        protocol.update(dict(self.protocol))
        reporting = dict(_DEFAULT_REPORTING)
        reporting.update(dict(self.reporting))
        object.__setattr__(self, "actions", tuple(normalized_actions))
        object.__setattr__(self, "protocol", protocol)
        object.__setattr__(self, "reporting", reporting)
        object.__setattr__(self, "integration", dict(self.integration))

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "PluginManifest":
        if not isinstance(payload, Mapping):
            raise ValueError("manifest must be an object")
        actions = payload.get("actions")
        if not isinstance(actions, (list, tuple)):
            raise ValueError("manifest actions must be an array")
        return cls(
            plugin_id=payload.get("plugin_id"),
            label=payload.get("label"),
            version=payload.get("version"),
            actions=tuple(actions),
            schema_version=payload.get("schema_version", "1.0"),
            protocol=payload.get("protocol") or {},
            reporting=payload.get("reporting") or {},
            integration=payload.get("integration") or {},
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plugin_id": self.plugin_id,
            "label": self.label,
            "version": self.version,
            "protocol": dict(self.protocol),
            "reporting": dict(self.reporting),
            "actions": [dict(action) for action in self.actions],
            "integration": dict(self.integration),
        }
