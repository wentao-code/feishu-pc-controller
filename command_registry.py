"""Map human Feishu commands to stable gateway actions."""

from __future__ import annotations

from dataclasses import dataclass

from plugin_registry import (
    PluginRegistry,
    builtin_plugin_specs,
    normalize_plugin_command,
)


_PLUGIN_CATEGORIES = {
    "bilibili-hiatus-analyzer": 1,
    "douyin-downloader-main": 2,
    "local_video_renamer": 3,
    "quark_file_management": 4,
}
_ACTION_SUFFIXES = {"start": 1, "stop": 2, "status": 3}
def _command_code(plugin_id: str, action: str) -> str | None:
    category = _PLUGIN_CATEGORIES.get(plugin_id)
    suffix = _ACTION_SUFFIXES.get(action)
    if category is None or suffix is None:
        return None
    return f"{category}{suffix:02d}"


@dataclass(frozen=True)
class ActionSpec:
    action: str
    target: str
    target_action: str
    label: str


_GLOBAL_COMMANDS = {
    "001": ActionSpec("system.shutdown", "all", "shutdown", "关机"),
    "002": ActionSpec("system.cancel_shutdown", "all", "cancel_shutdown", "取消关机"),
    "003": ActionSpec("system.status", "all", "status", "系统状态"),
    "004": ActionSpec("system.help", "all", "help", "指令集合"),
}


def normalize_command(text: str) -> str | None:
    resolved = CommandRegistry().resolve(text)
    return resolved.action if resolved is not None else None


class CommandRegistry:
    def __init__(self, plugins: PluginRegistry | None = None) -> None:
        self.plugins = plugins or PluginRegistry(builtin_plugin_specs())

    def register(self, plugin) -> None:
        self.plugins.register(plugin)

    def resolve(self, command: str) -> ActionSpec | None:
        normalized = normalize_plugin_command(command)
        if normalized in _GLOBAL_COMMANDS:
            return _GLOBAL_COMMANDS[normalized]
        if normalized in {"状态", "status", "systemstatus"}:
            return ActionSpec("system.status", "all", "status", "系统状态")
        if len(normalized) == 3 and normalized.isdigit():
            category, suffix = int(normalized[0]), int(normalized[1:])
            for plugin in self.plugins:
                if _PLUGIN_CATEGORIES.get(plugin.plugin_id) != category:
                    continue
                action_name = next(
                    (name for name, code_suffix in _ACTION_SUFFIXES.items() if code_suffix == suffix),
                    None,
                )
                action = next(
                    (item for item in plugin.actions if item.name == action_name),
                    None,
                )
                if action is not None:
                    return self._action_spec(plugin, action.name, action.label)
            return None
        resolved = self.plugins.resolve(command)
        if resolved is None:
            normalized_alias = normalize_plugin_command(command)
            for plugin in self.plugins:
                for action in plugin.actions:
                    if normalized_alias in {
                        normalize_plugin_command(alias) for alias in action.aliases
                    }:
                        return self._action_spec(plugin, action.name, action.label)
            return None
        plugin, action = resolved
        return self._action_spec(plugin, action.name, action.label)

    @staticmethod
    def _action_spec(plugin, action_name: str, label: str) -> ActionSpec:
        return ActionSpec(
            f"{plugin.action_namespace}.{action_name}",
            plugin.plugin_id,
            action_name,
            label,
        )

    def action_specs(self) -> tuple[ActionSpec, ...]:
        specs = [
            self._action_spec(plugin, action.name, action.label)
            for plugin in self.plugins
            for action in plugin.actions
        ]
        return tuple(
            sorted(
                specs,
                key=lambda spec: (
                    _command_code(spec.target, spec.target_action) is None,
                    _command_code(spec.target, spec.target_action) or "999",
                ),
            )
        )

    def help_text(self) -> str:
        registry = self
        lines = ["可用指令："]
        current_plugin_id = None
        for spec in registry.action_specs():
            plugin = registry.plugins.get(spec.target)
            action = next(item for item in plugin.actions if item.name == spec.target_action)
            if plugin.plugin_id != current_plugin_id:
                lines.append(f"{plugin.label}：")
                current_plugin_id = plugin.plugin_id
            aliases = " / ".join(action.aliases)
            code = _command_code(plugin.plugin_id, action.name)
            prefix = f"{code}. " if code else "- "
            lines.append(f"{prefix}{aliases}：{action.label}")
        return "\n".join(lines)
