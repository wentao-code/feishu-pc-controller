# Feishu PC Controller

This process is the local Feishu control and notification gateway. It supports
owner-only commands:

```text
抖音：开始运行  -> bilibili-hiatus-analyzer
抖音：停止运行  -> safely stop bilibili-hiatus-analyzer
抖音：开始下载  -> douyin-downloader-main
抖音：停止下载  -> safely stop douyin-downloader-main after the current video
状态            -> status of every registered system
```

The gateway never receives paths, filters, UID counts, or other execution
parameters from Feishu. The analyzer command is accepted only when its GUI is
running, the selected platform is Douyin, the configuration is locked, and no
task is active. The downloader command is accepted only when its GUI is
running, its settings are ready, and no task is active. Rejections are sent to
Feishu with the reason.

## Configuration

Copy `.env.example` to `.env` and fill in the Feishu credentials and a random
`FEISHU_CONTROL_TOKEN`. The same token and these variables must be available to
the two GUI processes through their Windows user/system environment:

```text
FEISHU_CONTROL_TOKEN=the_same_token
FEISHU_CONTROLLER_REPORT_URL=http://127.0.0.1:8760
FEISHU_BILIBILI_HIATUS_ANALYZER_PORT=8761
FEISHU_DOUYIN_DOWNLOADER_MAIN_PORT=8762
```

The ports are loopback-only. Do not expose them through firewall port
forwarding.

## Startup order

1. Set the shared environment variables in `.env`.
2. Start `start_feishu_bot.bat`. It loads this project's `.env` and launches
   only the Feishu controller. Start each target application with its own
   launcher; the controller monitors its endpoint and sends commands only
   while that application is available.
3. Make `FEISHU_CONTROL_TOKEN` available to each target application's process
   when starting it. Lock the bilibili-hiatus-analyzer configuration before sending
   `抖音：开始运行`.

## Plugin SDK

The reusable `feishu_plugin_sdk` package provides the authenticated loopback
control server and task report client used by GUI plugins. Install it into the
same Python environment used by each plugin:

```powershell
python -m pip install -e D:\pycharm_pro\feishu-pc-controller
```

`bilibili-hiatus-analyzer` and `douyin-downloader-main` keep their established
`backend.remote_control`, `backend.report_client`, `remote_control`, and
`report_client` import paths as compatibility wrappers. New plugins should
import directly from `feishu_plugin_sdk`.

## Dynamic Plugin Registry

The preferred configuration is an explicit list of plugin endpoints. The
controller fetches and validates each plugin's authenticated
`GET /api/v1/manifest`, then creates the registry from the returned actions:

```env
FEISHU_PLUGIN_ENDPOINTS_JSON=[{"id":"local_video_renamer","url":"http://127.0.0.1:8763"},{"id":"quark_file_management","url":"http://127.0.0.1:8764"}]
```

The endpoint list is explicit and local-only; the controller never scans the
network. If a configured endpoint is unreachable during startup, it remains in
the registry as a status-only entry and reports `系统未启动` when its control
port refuses a connection. Its start/stop actions are loaded from the Manifest
when the endpoint is available during controller startup. The configured `id`
must match the Manifest's `plugin_id`. Readiness fields and refusal messages
may be supplied as endpoint policy overrides when needed.

For compatibility, the controller can also load plugin definitions from
`FEISHU_PLUGINS_JSON`. Each entry declares an `id`, display `label`, loopback
`url`, `start`/`stop` action aliases, and optional readiness fields. For example:

```json
[{"id":"video_tools","label":"视频工具","url":"http://127.0.0.1:9001","actions":[{"name":"start","label":"视频处理","aliases":["视频工具：开始处理"]},{"name":"stop","label":"停止视频处理","aliases":["视频工具：停止处理"]}],"required_ready_fields":["ready"]}]
```

Configuration uses `FEISHU_PLUGIN_ENDPOINTS_JSON` to add manifest-driven
plugins. If a discovered plugin uses the same ID as a built-in plugin, the
discovered definition replaces that built-in entry; otherwise the built-in
analyzer and downloader entries remain available. `FEISHU_PLUGINS_JSON` remains
the full replacement mode for advanced static registries. When both JSON
registry variables are absent, `FEISHU_BILIBILI_HIATUS_ANALYZER_URL` and
`FEISHU_DOUYIN_DOWNLOADER_MAIN_URL` configure the built-in plugin endpoints.
The controller creates one authenticated `ControlClient` per registered plugin
and generates help/status output from the registry.

The controller report database is stored under `runtime/` and deduplicates
reports by `event_id`. Feishu notification failures are retried and do not
change the task result.

Stop commands have two phases. The bot first replies that the stop request was
submitted. The target GUI then calls its existing stop method and reports the
final `cancelled` result after the current safe checkpoint:

```text
空闲时停止       -> 当前没有正在运行的任务，无需停止。
运行中停止       -> 停止请求已提交，当前处理完成后会安全停止。
停止完成         -> task report with cancelled status and final metrics
```

## Local endpoints

The controller exposes:

```text
GET  /api/v1/health
GET  /api/v1/system/status
POST /api/v1/task-reports
```

The two GUI processes expose the same authenticated status and command paths on
ports 8761 and 8762:

```text
GET  /api/v1/manifest
GET  /api/v1/status
POST /api/v1/commands   {"request_id":"...","action":"start"}
```

The complete plugin manifest, command, timeout, stop, and task-report contract
is documented in [docs/CONTROL_PROTOCOL.md](docs/CONTROL_PROTOCOL.md).

## Controller startup and autostart

`start_feishu_bot.bat` loads the controller `.env` and starts only the Feishu
controller. It does not launch, restart, or stop the analyzer, downloader, or
other plugins. Their status is read from their loopback control endpoints; a
command is sent only when the endpoint is available. The Local Video Renamer
and Quark services currently expose unbound adapters and will reject business
commands until their GUI callbacks are connected.

Run `powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1` once to
register the controller-only launcher at Windows logon. Remove it with
`uninstall_autostart.ps1`.
