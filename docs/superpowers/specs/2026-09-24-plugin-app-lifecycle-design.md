# Plugin Application Lifecycle Design

## Goal

Add Feishu commands to start and close the four registered applications without changing existing task start/stop behavior.

## Commands

| Project | Start | Close |
| --- | --- | --- |
| `bilibili-hiatus-analyzer` | `104` `bilibili-hiatus-analyzer：启动项目` | `105` `bilibili-hiatus-analyzer：关闭项目` |
| `douyin-downloader-main` | `204` `douyin-downloader-main：启动项目` | `205` `douyin-downloader-main：关闭项目` |
| `local_video_renamer` | `304` `Local Video Renamer：启动项目` | `305` `Local Video Renamer：关闭项目` |
| `quark_file_management` | `404` `Quark File Management：启动项目` | `405` `Quark File Management：关闭项目` |

Each code is also listed with an explicit Chinese command in the help text. Existing task commands and aliases remain unchanged.

## Design

The controller owns a fixed allowlist of project roots and launch entrypoints: analyzer `start_gui.bat`, downloader `run.py --gui` using the controller interpreter, LVR `start_vidnorm.bat`, and Quark `start_web.bat`. It checks health before launch, starts only when not already running, and waits for readiness before reporting success. Feishu input cannot supply a path or shell command.

For the three GUI applications, the authenticated loopback control protocol gains a distinct application-close action. The target GUI handles it on its main thread through its existing close lifecycle. A busy task causes a refusal with a clear message; it is never force-terminated.

Quark lifecycle commands target the Web application started by its existing `start_web.bat`. The controller tracks only the Streamlit process it launched and requests a graceful console shutdown. If a healthy Quark web server exists but is not owned by this controller instance, close is refused rather than terminating an unverified process.

Application lifecycle commands are separate from task `start` and `stop`, and status continues to report both application presence and task activity.

## Failure Handling

- Already-running applications are not launched twice.
- Startup reports failure if the entrypoint is missing, exits early, or fails its readiness check.
- Close reports the busy refusal while a task is active.
- Close reports an unmanaged-instance refusal when safe ownership cannot be established.
- No lifecycle path uses forced process termination.

## Verification

- Controller tests cover all command numbers, help text, start idempotency, readiness timeout, busy close refusal, and close routing.
- GUI adapter tests verify close is queued to the GUI thread, uses existing close handlers, and is refused while busy.
- Quark tests cover managed Streamlit start, graceful stop, and unmanaged-instance refusal.
- Run the focused test suites for all four repositories.
