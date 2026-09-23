import pytest

from feishu_plugin_sdk.manifest import PluginManifest


def test_manifest_round_trip_preserves_plugin_contract():
    manifest = PluginManifest(
        plugin_id="video_tools",
        label="视频工具",
        version="1.0.0",
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

    restored = PluginManifest.from_json(manifest.to_json())

    assert restored.to_json() == manifest.to_json()
    assert restored.to_json()["protocol"]["manifest"] == "/api/v1/manifest"


def test_manifest_accepts_read_only_status_action():
    manifest = PluginManifest(
        plugin_id="status_plugin",
        label="状态插件",
        version="1.0.0",
        actions=(
            {"name": "status", "label": "查看状态", "aliases": ["状态插件：状态"]},
        ),
    )

    assert manifest.to_json()["actions"][0]["name"] == "status"


def test_manifest_rejects_duplicate_action_names_and_unsupported_actions():
    with pytest.raises(ValueError, match="duplicate action"):
        PluginManifest(
            plugin_id="video_tools",
            label="视频工具",
            version="1.0.0",
            actions=(
                {"name": "start", "label": "开始", "aliases": ["start"]},
                {"name": "start", "label": "再次开始", "aliases": ["start again"]},
            ),
        )

    with pytest.raises(ValueError, match="unsupported action"):
        PluginManifest(
            plugin_id="video_tools",
            label="视频工具",
            version="1.0.0",
            actions=({"name": "restart", "label": "重启", "aliases": ["restart"]},),
        )
