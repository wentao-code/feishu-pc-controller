import pytest

from command_registry import CommandRegistry
from feishu_plugin_sdk.manifest import PluginManifest
from plugin_registry import PluginAction, PluginRegistry, PluginSpec


def _plugin(plugin_id="video_tools", label="视频工具", url="http://127.0.0.1:9001"):
    return PluginSpec(
        plugin_id=plugin_id,
        label=label,
        base_url=url,
        actions=(
            PluginAction(
                name="start",
                label="视频处理",
                aliases=("视频工具：开始处理", "video tools start"),
            ),
            PluginAction(
                name="stop",
                label="停止视频处理",
                aliases=("视频工具：停止处理", "video tools stop"),
            ),
        ),
    )


def test_registry_resolves_registered_plugin_actions_without_code_changes():
    registry = PluginRegistry([_plugin()])

    resolved = CommandRegistry(registry).resolve("视频工具：开始处理")

    assert resolved.action == "video_tools.start"
    assert resolved.target == "video_tools"
    assert resolved.target_action == "start"
    assert resolved.label == "视频处理"


def test_registry_rejects_duplicate_plugin_ids_and_action_names():
    registry = PluginRegistry()
    registry.register(_plugin())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(_plugin())

    with pytest.raises(ValueError, match="unsupported plugin action"):
        registry.register(
            PluginSpec(
                plugin_id="other",
                label="其他",
                base_url="http://127.0.0.1:9002",
                actions=(PluginAction("restart", "重启", ("其他：重启",)),),
            )
        )


def test_registry_help_text_is_generated_from_registered_plugins():
    registry = CommandRegistry(PluginRegistry([_plugin()]))

    help_text = registry.help_text()

    assert "视频工具：开始处理" in help_text
    assert "视频工具：停止处理" in help_text
    assert "video tools start" in help_text


def test_plugin_spec_from_manifest_uses_manifest_actions_and_policy_overrides():
    manifest = PluginManifest(
        plugin_id="video_tools",
        label="视频工具",
        version="1.2.0",
        actions=(
            {
                "name": "start",
                "label": "开始处理",
                "aliases": ["视频工具：开始处理"],
            },
            {
                "name": "stop",
                "label": "停止处理",
                "aliases": ["视频工具：停止处理"],
            },
        ),
    )

    spec = PluginSpec.from_manifest(
        manifest,
        "http://127.0.0.1:9001",
        required_ready_fields=("ready",),
        refusal_messages={"ready": "视频工具未准备好"},
        action_namespace="video.tools",
    )

    assert spec.plugin_id == "video_tools"
    assert spec.label == "视频工具"
    assert spec.base_url == "http://127.0.0.1:9001"
    assert [action.label for action in spec.actions] == ["开始处理", "停止处理"]
    assert spec.actions[0].aliases == ("视频工具：开始处理",)
    assert spec.required_ready_fields == ("ready",)
    assert spec.refusal_messages["ready"] == "视频工具未准备好"
    assert spec.action_namespace == "video.tools"


def test_registry_from_manifests_rejects_duplicate_ids():
    manifest = PluginManifest(
        plugin_id="video_tools",
        label="视频工具",
        version="1.0.0",
        actions=({"name": "start", "label": "开始", "aliases": ["开始"]},),
    )

    with pytest.raises(ValueError, match="already registered"):
        PluginRegistry.from_manifests(
            (
                (manifest, "http://127.0.0.1:9001", {}),
                (manifest, "http://127.0.0.1:9002", {}),
            )
        )
