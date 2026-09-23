# Manifest-Driven Plugin Registration Design

## Goal

让 `feishu-pc-controller` 使用插件自己的 `/api/v1/manifest` 作为能力来源，在保持现有静态注册和 legacy 插件兼容的前提下，动态校验并注册独立插件。

## Scope

本阶段只修改主控注册流程和公共客户端，不绑定 Local Video Renamer 的 GUI 按钮，不改变 Quark 的任务执行方式，也不做局域网扫描。

## Architecture

主控读取一个显式的插件端点列表 `FEISHU_PLUGIN_ENDPOINTS_JSON`。每个端点包含插件 ID、HTTP URL，以及可选的注册覆盖配置。启动时，主控用共享控制 token 请求 `/api/v1/manifest`，通过公共 `PluginManifest` 校验后转换为现有 `PluginSpec`，再交给动态 `PluginRegistry`。

Manifest 获取失败、鉴权失败或内容非法时，只跳过该插件并记录可诊断原因；其他插件和 legacy 配置继续工作。未配置显式端点时保留当前 `FEISHU_PLUGINS_JSON` 和两个内置插件的行为。

## Configuration

```env
FEISHU_PLUGIN_ENDPOINTS_JSON=[
  {"id":"local_video_renamer","url":"http://127.0.0.1:8763"},
  {"id":"quark_file_management","url":"http://127.0.0.1:8764"}
]
```

The endpoint list is explicit and local-only. The controller never probes
arbitrary hosts or ports. `id` must match the Manifest `plugin_id`.

Optional endpoint fields can override registry-only policy that a plugin does
not need to expose in its public Manifest:

- `required_ready_fields`
- `required_status_values`
- `refusal_messages`
- `status_messages`
- `action_namespace`

The Manifest remains authoritative for action names, labels, and aliases.

## Data Flow

```text
FEISHU_PLUGIN_ENDPOINTS_JSON
        |
        v
ManifestClient.fetch(endpoint)
        |
        v
PluginManifest.from_json(payload)
        |
        v
PluginSpec.from_manifest(...)
        |
        v
PluginRegistry -> ControllerService -> ControlClient
```

## Failure Handling

- Missing or malformed endpoint configuration raises a clear configuration error.
- A plugin HTTP timeout, HTTP error, invalid JSON, or Manifest validation error
  excludes only that plugin.
- Duplicate IDs are rejected before controller startup completes.
- If all explicitly configured endpoints fail, the controller starts with an
  empty dynamic registry and reports those failures in startup logs; it does
  not silently fall back to unrelated legacy endpoints.
- Existing static `FEISHU_PLUGINS_JSON` remains supported when the new endpoint
  variable is absent.

## Testing

Tests cover authenticated Manifest fetch, conversion into `PluginSpec`, policy
overrides, malformed Manifest rejection, an offline plugin alongside a healthy
plugin, and controller command routing through a discovered plugin. Existing
legacy and full-suite tests remain unchanged.
