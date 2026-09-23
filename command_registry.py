"""Map human Feishu commands to stable gateway actions."""

from __future__ import annotations

from dataclasses import dataclass

from plugin_registry import PluginRegistry, legacy_plugin_specs, normalize_plugin_command


@dataclass(frozen=True)
class ActionSpec:
    action: str
    target: str
    target_action: str
    label: str


def normalize_command(text: str) -> str | None:
    resolved = CommandRegistry().resolve(text)
    return resolved.action if resolved is not None else None


class CommandRegistry:
    def __init__(self, plugins: PluginRegistry | None = None) -> None:
        self.plugins = plugins or PluginRegistry(legacy_plugin_specs())

    def register(self, plugin) -> None:
        self.plugins.register(plugin)

    def resolve(self, command: str) -> ActionSpec | None:
        normalized = normalize_plugin_command(command)
        if normalized in {"状态", "status", "systemstatus"}:
            return ActionSpec("system.status", "all", "status", "系统状态")
        resolved = self.plugins.resolve(command)
        if resolved is None:
            return None
        plugin, action = resolved
        return ActionSpec(
            f"{plugin.action_namespace}.{action.name}",
            plugin.plugin_id,
            action.name,
            action.label,
        )

    def action_specs(self) -> tuple[ActionSpec, ...]:
        return tuple(
            ActionSpec(f"{plugin.action_namespace}.{action.name}", plugin.plugin_id, action.name, action.label)
            for plugin in self.plugins
            for action in plugin.actions
        )

    def help_text(self) -> str:
        registry = self
        lines = ["可用指令："]
        for index, spec in enumerate(registry.action_specs(), start=1):
            plugin = registry.plugins.get(spec.target)
            action = next(item for item in plugin.actions if item.name == spec.target_action)
            aliases = " / ".join(action.aliases)
            lines.append(f"{index}. {aliases}：{action.label}")
        lines.append("状态 / status：查看所有已注册插件的运行状态")
        lines.append("帮助 / help：显示本指令列表")
        return "\n".join(lines)
