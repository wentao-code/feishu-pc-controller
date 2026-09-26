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
_PROJECT_LABELS = {
    "bilibili-hiatus-analyzer": "bilibili-hiatus-analyzer",
    "douyin-downloader-main": "douyin-downloader-main",
    "local_video_renamer": "Local Video Renamer",
    "quark_file_management": "Quark File Management",
}
_LIFECYCLE_ALIASES = {
    "bilibili-hiatus-analyzer": ("bilibili-hiatus-analyzer：启动项目", "bilibili-hiatus-analyzer：关闭项目"),
    "douyin-downloader-main": ("douyin-downloader-main：启动项目", "douyin-downloader-main：关闭项目"),
    "local_video_renamer": ("Local Video Renamer：启动项目", "Local Video Renamer：关闭项目"),
    "quark_file_management": ("Quark File Management：启动项目", "Quark File Management：关闭项目"),
}
_ACTION_SUFFIXES = {"start": 1, "stop": 2, "status": 3, "launch": 4, "close": 5}
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
            lifecycle_action = next(
                (name for name in ("launch", "close") if _ACTION_SUFFIXES[name] == suffix),
                None,
            )
            if lifecycle_action is not None:
                plugin_id = next(
                    (name for name, value in _PLUGIN_CATEGORIES.items() if value == category),
                    None,
                )
                if plugin_id is not None:
                    return self._lifecycle_spec(plugin_id, lifecycle_action)
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
        normalized_alias = normalize_plugin_command(command)
        for plugin_id, aliases in _LIFECYCLE_ALIASES.items():
            for action_name, alias in zip(("launch", "close"), aliases):
                if normalized_alias == normalize_plugin_command(alias):
                    return self._lifecycle_spec(plugin_id, action_name)
        resolved = self.plugins.resolve(command)
        if resolved is None:
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

    @staticmethod
    def _lifecycle_spec(plugin_id: str, action_name: str) -> ActionSpec:
        label = "启动项目" if action_name == "launch" else "关闭项目"
        return ActionSpec(
            f"application.{action_name}",
            plugin_id,
            action_name,
            label,
        )

    def action_specs(self) -> tuple[ActionSpec, ...]:
        specs = [
            self._action_spec(plugin, action.name, action.label)
            for plugin in self.plugins
            for action in plugin.actions
        ]
        specs.extend(
            self._lifecycle_spec(plugin_id, action_name)
            for plugin_id in _PLUGIN_CATEGORIES
            for action_name in ("launch", "close")
        )
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
            project_label = _PROJECT_LABELS.get(spec.target, plugin.label if plugin else spec.target)
            if spec.target != current_plugin_id:
                lines.append(f"{project_label}：")
                current_plugin_id = spec.target
            if spec.action.startswith("application."):
                action_name = spec.target_action
                aliases = _LIFECYCLE_ALIASES[spec.target][0 if action_name == "launch" else 1]
                action_label = None
            else:
                action = next(item for item in plugin.actions if item.name == spec.target_action)
                aliases = " / ".join(action.aliases)
                action_label = action.label
            code = _command_code(spec.target, spec.target_action)
            prefix = f"{code}. " if code else "- "
            suffix = f"：{action_label}" if action_label else ""
            lines.append(f"{prefix}{aliases}{suffix}")
        return "\n".join(lines)
