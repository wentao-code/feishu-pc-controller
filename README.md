# Feishu PC Controller

This process is the local Feishu control and notification gateway. It supports
two owner-only commands:

```text
抖音：开始运行  -> main analyzer GUI
抖音：开始下载  -> Douyin downloader GUI
状态            -> status of both GUIs
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
FEISHU_MAIN_ANALYZER_PORT=8761
FEISHU_DOUYIN_DOWNLOADER_PORT=8762
```

The ports are loopback-only. Do not expose them through firewall port
forwarding.

## Startup order

1. Set the shared environment variables.
2. Start the main analyzer GUI and lock its configuration.
3. Start `douyin-downloader-main/run.py --gui` if video downloads are needed.
4. Start `start_feishu_bot.bat` or `start_feishu_bot_background.bat`.

The controller report database is stored under `runtime/` and deduplicates
reports by `event_id`. Feishu notification failures are retried and do not
change the task result.

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
GET  /api/v1/status
POST /api/v1/commands   {"request_id":"...","action":"start"}
```
