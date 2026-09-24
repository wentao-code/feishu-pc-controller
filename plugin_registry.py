"""Runtime plugin registration and manifest-shaped command metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from feishu_plugin_sdk.manifest import PluginManifest

_SUPPORTED_PLUGIN_ACTIONS = frozenset({"start", "stop", "status"})
_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_\-]{1,63}$")
_DISPLAY_LABELS = {
    "bilibili-hiatus-analyzer": "bilibili-hiatus-analyzer",
    "douyin-downloader-main": "douyin-downloader-main",
}


def _text(value: Any, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{name} is required")
    return result


def normalize_plugin_command(value: str) -> str:
    """Normalize aliases without changing their human-readable form."""
    return "".join(str(value or "").strip().lower().split()).replace("：", "").replace(":", "")


@dataclass(frozen=True)
class PluginAction:
    name: str
    label: str
    aliases: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.name not in _SUPPORTED_PLUGIN_ACTIONS:
            raise ValueError(f"unsupported plugin action: {self.name}")
        if not self.aliases or any(not str(alias).strip() for alias in self.aliases):
            raise ValueError(f"aliases are required for plugin action: {self.name}")
        object.__setattr__(self, "label", _text(self.label, "action label"))
        object.__setattr__(
            self,
            "aliases",
            tuple(_text(alias, "action alias") for alias in self.aliases),
        )

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "PluginAction":
        aliases = payload.get("aliases") or payload.get("commands") or ()
        if isinstance(aliases, str):
            aliases = (aliases,)
        if not isinstance(aliases, (list, tuple)):
            raise ValueError("plugin action aliases must be an array")
        return cls(
            name=_text(payload.get("name"), "plugin action name"),
            label=_text(payload.get("label"), "plugin action label"),
            aliases=tuple(str(alias) for alias in aliases),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class PluginSpec:
    plugin_id: str
    label: str
    base_url: str
    actions: tuple[PluginAction, ...]
    required_ready_fields: tuple[str, ...] = ()
    required_status_values: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    refusal_messages: Mapping[str, str] = field(default_factory=dict)
    status_messages: Mapping[str, str] = field(default_factory=dict)
    action_namespace: str | None = None

    def __post_init__(self) -> None:
        plugin_id = _text(self.plugin_id, "plugin id").lower()
        if not _PLUGIN_ID.fullmatch(plugin_id):
            raise ValueError("plugin id must be 2-64 lowercase letters, digits, '_' or '-'")
        actions = tuple(self.actions)
        if not actions:
            raise ValueError(f"plugin {plugin_id} must declare at least one action")
        action_names = [action.name for action in actions]
        if len(set(action_names)) != len(action_names):
            raise ValueError(f"plugin {plugin_id} declares duplicate actions")
        aliases = [normalize_plugin_command(alias) for action in actions for alias in action.aliases]
        if len(set(aliases)) != len(aliases):
            raise ValueError(f"plugin {plugin_id} declares duplicate command aliases")
        object.__setattr__(self, "plugin_id", plugin_id)
        object.__setattr__(
            self,
            "label",
            _DISPLAY_LABELS.get(plugin_id, _text(self.label, "plugin label")),
        )
        object.__setattr__(self, "base_url", _text(self.base_url, "plugin url").rstrip("/"))
        object.__setattr__(self, "actions", actions)
        object.__setattr__(
            self,
            "action_namespace",
            _text(self.action_namespace or plugin_id, "action namespace"),
        )
        object.__setattr__(
            self,
            "required_ready_fields",
            tuple(_text(value, "required status field") for value in self.required_ready_fields),
        )
        object.__setattr__(
            self,
            "required_status_values",
            {str(key): tuple(values) for key, values in self.required_status_values.items()},
        )
        object.__setattr__(
            self,
            "refusal_messages",
            {str(key): str(value) for key, value in self.refusal_messages.items()},
        )
        object.__setattr__(
            self,
            "status_messages",
            {str(key): str(value) for key, value in self.status_messages.items()},
        )

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "PluginSpec":
        actions = payload.get("actions")
        if not isinstance(actions, (list, tuple)):
            raise ValueError("plugin actions must be an array")
        required_values = payload.get("required_status_values") or {}
        if not isinstance(required_values, Mapping):
            raise ValueError("required_status_values must be an object")
        return cls(
            plugin_id=_text(payload.get("id") or payload.get("plugin_id"), "plugin id"),
            label=_text(payload.get("label"), "plugin label"),
            base_url=_text(payload.get("url") or payload.get("base_url"), "plugin url"),
            actions=tuple(PluginAction.from_json(action) for action in actions),
            required_ready_fields=tuple(payload.get("required_ready_fields") or ()),
            required_status_values={
                str(key): tuple(values) if isinstance(values, (list, tuple)) else (values,)
                for key, values in required_values.items()
            },
            refusal_messages=dict(payload.get("refusal_messages") or {}),
            status_messages=dict(payload.get("status_messages") or {}),
            action_namespace=payload.get("action_namespace"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.plugin_id,
            "label": self.label,
            "url": self.base_url,
            "actions": [action.to_json() for action in self.actions],
            "required_ready_fields": list(self.required_ready_fields),
            "required_status_values": {
                key: list(values) for key, values in self.required_status_values.items()
            },
            "refusal_messages": dict(self.refusal_messages),
            "status_messages": dict(self.status_messages),
            "action_namespace": self.action_namespace,
        }

    @classmethod
    def from_manifest(
        cls,
        manifest: PluginManifest,
        base_url: str,
        **policy_overrides: Any,
    ) -> "PluginSpec":
        """Build controller policy from a validated plugin capability manifest."""
        if not isinstance(manifest, PluginManifest):
            raise TypeError("manifest must be a PluginManifest")
        actions = tuple(
            PluginAction(
                name=str(action["name"]),
                label=str(action["label"]),
                aliases=tuple(str(alias) for alias in action["aliases"]),
            )
            for action in manifest.actions
        )
        allowed = {
            "required_ready_fields",
            "required_status_values",
            "refusal_messages",
            "status_messages",
            "action_namespace",
        }
        unknown = set(policy_overrides) - allowed
        if unknown:
            raise ValueError(
                "unsupported manifest policy override(s): "
                + ", ".join(sorted(unknown))
            )
        return cls(
            plugin_id=manifest.plugin_id,
            label=manifest.label,
            base_url=base_url,
            actions=actions,
            required_ready_fields=tuple(policy_overrides.get("required_ready_fields", ())),
            required_status_values=dict(policy_overrides.get("required_status_values", {})),
            refusal_messages=dict(policy_overrides.get("refusal_messages", {})),
            status_messages=dict(policy_overrides.get("status_messages", {})),
            action_namespace=policy_overrides.get("action_namespace"),
        )


class PluginRegistry:
    """Mutable registry used by the controller service at runtime."""

    def __init__(self, plugins: Iterable[PluginSpec] = ()) -> None:
        self._plugins: dict[str, PluginSpec] = {}
        for plugin in plugins:
            self.register(plugin)

    def register(self, plugin: PluginSpec) -> None:
        if plugin.plugin_id in self._plugins:
            raise ValueError(f"plugin already registered: {plugin.plugin_id}")
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> PluginSpec | None:
        return self._plugins.get(plugin_id)

    def __iter__(self):
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    def resolve(self, command: str) -> tuple[PluginSpec, PluginAction] | None:
        normalized = normalize_plugin_command(command)
        if normalized in {"状态", "status", "systemstatus"}:
            return None
        for plugin in self._plugins.values():
            for action in plugin.actions:
                if normalized in {normalize_plugin_command(alias) for alias in action.aliases}:
                    return plugin, action
        return None

    @classmethod
    def from_json(cls, raw: str) -> "PluginRegistry":
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("FEISHU_PLUGINS_JSON must be valid JSON") from error
        if not isinstance(payload, list):
            raise ValueError("FEISHU_PLUGINS_JSON must be a JSON array")
        try:
            return cls(PluginSpec.from_json(item) for item in payload)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid FEISHU_PLUGINS_JSON: {error}") from error

    @classmethod
    def from_manifests(
        cls,
        entries: Iterable[tuple[PluginManifest, str, Mapping[str, Any]]],
    ) -> "PluginRegistry":
        return cls(
            PluginSpec.from_manifest(manifest, base_url, **dict(policy))
            for manifest, base_url, policy in entries
        )


def builtin_plugin_specs(
    bilibili_hiatus_analyzer_url: str = "http://127.0.0.1:8761",
    douyin_downloader_main_url: str = "http://127.0.0.1:8762",
) -> tuple[PluginSpec, ...]:
    """Build the two first-party project registrations."""
    return (
        PluginSpec(
            plugin_id="bilibili-hiatus-analyzer",
            label="bilibili-hiatus-analyzer",
            base_url=bilibili_hiatus_analyzer_url,
            actions=(
                PluginAction("start", "抖音抓取", ("抖音：开始运行",)),
                PluginAction("stop", "停止抖音抓取", ("抖音：停止运行",)),
                PluginAction("status", "查看抖音抓取状态", ("抖音：状态",)),
            ),
            required_ready_fields=("config_locked",),
            refusal_messages={
                "gui_running": "主程序未运行",
                "busy": "主程序当前已有任务运行中",
                "config_locked": "当前配置未锁定，请先在主程序中锁定配置",
            },
            status_messages={"config_locked": "未锁定配置"},
            action_namespace="douyin.fetch",
        ),
        PluginSpec(
            plugin_id="douyin-downloader-main",
            label="douyin-downloader-main",
            base_url=douyin_downloader_main_url,
            actions=(
                PluginAction("start", "抖音视频下载", ("抖音：开始下载",)),
                PluginAction("stop", "停止抖音下载", ("抖音：停止下载",)),
                PluginAction("status", "查看抖音下载状态", ("抖音下载：状态",)),
            ),
            required_ready_fields=("ready",),
            refusal_messages={
                "gui_running": "抖音下载程序未运行",
                "busy": "抖音下载程序当前已有任务运行中",
                "ready": "抖音下载程序当前未准备好",
            },
            status_messages={"ready": "未准备好"},
            action_namespace="douyin.download",
        ),
    )
