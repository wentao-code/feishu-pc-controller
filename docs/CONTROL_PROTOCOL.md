# Feishu Plugin Control Protocol

This document is the contract between `feishu-pc-controller` and a local
plugin. A plugin is an independent process. It owns its GUI state, task
execution, cancellation behavior, and final task report.

## Transport and Authentication

- Bind the plugin HTTP server to `127.0.0.1`.
- Require `Authorization: Bearer <FEISHU_CONTROL_TOKEN>` on every endpoint.
- Use JSON with UTF-8 encoding.
- Do not accept paths, filters, credentials, browser options, or arbitrary
  Python arguments in a command request.

The shared SDK provides this transport through
`feishu_plugin_sdk.RemoteControlServer`.

## Manifest

`GET /api/v1/manifest` returns the plugin capability description:

```json
{
  "schema_version": "1.0",
  "plugin_id": "local_video_renamer",
  "label": "Local Video Renamer",
  "version": "0.1.0",
  "protocol": {
    "manifest": "/api/v1/manifest",
    "status": "/api/v1/status",
    "commands": "/api/v1/commands"
  },
  "reporting": {
    "client": "feishu_plugin_sdk.ReportClient",
    "controller_path": "/api/v1/task-reports"
  },
  "actions": [
    {
      "name": "start",
      "label": "开始本地视频处理",
      "aliases": ["本地视频：开始处理"]
    },
    {
      "name": "stop",
      "label": "停止本地视频处理",
      "aliases": ["本地视频：停止处理"]
    }
  ],
  "integration": {
    "bound": false,
    "message": "等待宿主注入 GUI 业务回调"
  }
}
```

`actions[].name` is stable and limited to task `start`, `stop`, and read-only
`status`. Human aliases are consumed by the controller registry. A `status`
action reads `GET /api/v1/status` and never submits a task command. Application
lifecycle commands are controller-managed and are not declared as task manifest
actions.
`integration.bound=false` means the adapter is intentionally a scaffold and
must reject start/stop commands without invoking business code.

## Status

`GET /api/v1/status` returns a JSON object. Every plugin must provide:

```json
{
  "plugin_id": "local_video_renamer",
  "gui_running": true,
  "ready": true,
  "busy": false,
  "task_id": null
}
```

Plugins may add safe, non-secret fields. The controller uses `gui_running`,
`ready`, and `busy` as safety gates. An adapter may add fields such as
`config_locked`, `mode`, `queue_depth`, or `control_bound`.

## Commands

`POST /api/v1/commands` accepts task actions `start` and `stop`, plus the
distinct application action `shutdown`:

```json
{
  "request_id": "uuid-or-event-id",
  "action": "start"
}
```

The server queues the command for the owning GUI/event-loop thread. The
business callback is called only when that thread drains the queue. A normal
response is:

```json
{
  "request_id": "uuid-or-event-id",
  "accepted": true,
  "status": "accepted",
  "task_id": "task-id"
}
```

Rejections use `accepted=false`, `status="rejected"`, and a human-readable
`reason`. `start` requires a running, ready, idle plugin. `stop` requires a
running task. `shutdown` requires an idle GUI with no queued tasks and must
invoke the existing window-close path on the GUI/event-loop thread. It must not
stop or cancel a task as a side effect. A stop response acknowledges only that
the stop request was accepted; the plugin must continue processing its current
safe checkpoint and later publish a terminal `cancelled` report.

If the GUI thread does not drain the request before the bounded command
timeout, the server returns HTTP 504 and marks the queued command expired. An
expired command must never execute when the GUI later drains its queue.

Repeated `request_id` values are idempotent while a request is in flight and
after it has completed.

## Task Reports

Plugins use `feishu_plugin_sdk.ReportClient` to post a terminal report to the
controller at `POST /api/v1/task-reports`:

```json
{
  "event_id": "task-id:finished",
  "task_id": "task-id",
  "source": "local_video_renamer",
  "task_type": "video_processing",
  "status": "succeeded",
  "started_at": "2026-09-22T12:00:00+08:00",
  "finished_at": "2026-09-22T12:03:00+08:00",
  "elapsed_seconds": 180,
  "metrics": {"success": 10, "failed": 0, "skipped": 1},
  "details": {},
  "error": null
}
```

Valid terminal statuses are `succeeded`, `partial`, `failed`, and
`cancelled`. `event_id` is the report idempotency key. The controller stores
the first report for an event and sends at most one notification for it.

## Adding a Plugin

1. Install the shared SDK in the plugin's Python environment.
2. Create an adapter that owns a `StatusSnapshot`, `manifest()`, and
   `create_control_server()`.
3. Bind existing start/stop methods through callbacks; do not duplicate task
   logic in the adapter.
4. Drain commands on the plugin's GUI/event-loop thread.
5. Add the plugin to `FEISHU_PLUGINS_JSON` in the controller environment.
6. Test manifest discovery, readiness refusal, command delivery, timeout
   expiry, safe stop, and duplicate report submission.

The controller's numbered application lifecycle commands use fixed local
entrypoints and configured project roots. They never accept an executable,
path, or arguments from a Feishu message. Quark lifecycle commands target the
Streamlit Web process started by `start_web.bat`; an unmanaged Web process is
not terminated.

For runtime registration, use the controller's explicit endpoint list:

```env
FEISHU_PLUGIN_ENDPOINTS_JSON=[{"id":"local_video_renamer","url":"http://127.0.0.1:8763"}]
```

The controller fetches only the listed loopback endpoints. The configured ID
must match `manifest.plugin_id`; a failed endpoint is isolated. Discovered
plugins are added to the built-in legacy plugins, and a discovered plugin with
the same ID replaces its legacy entry. `FEISHU_PLUGINS_JSON` remains a full
replacement registry for static deployments.
