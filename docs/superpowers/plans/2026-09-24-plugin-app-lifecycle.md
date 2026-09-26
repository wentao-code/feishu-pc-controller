# Plugin Application Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add numbered Feishu commands to start and gracefully close the four integrated applications, independent of their existing task commands.

**Architecture:** The controller resolves fixed lifecycle command IDs and launches only known entrypoints after checking health. GUI projects expose an authenticated app-close action handled on their GUI thread; Quark Web is controlled only through a controller-owned Streamlit process. Busy applications refuse close, and unmanaged Quark processes are never terminated.

**Tech Stack:** Python, pytest, loopback HTTP, Qt/Tk event loops, Windows batch launchers, Streamlit.

## Global Constraints

- Preserve current dirty-worktree changes in all four repositories.
- Keep existing task `start`, `stop`, and status commands unchanged.
- Never accept an executable path or command line from a Feishu message.
- Never force-kill target processes.
- Lifecycle command IDs are 104/105, 204/205, 304/305, and 404/405.
- Quark lifecycle commands target the Web app launched by `start_web.bat`.
- Refuse app close while the target reports a running task.

---

### Task 1: Add lifecycle command registration

**Files:**
- Modify: `command_registry.py`
- Test: `tests/test_command_registry.py`

- [x] Add failing tests resolving all eight numeric IDs and checking help output distinguishes application start/close from task start/stop.
- [x] Run `pytest tests/test_command_registry.py -q` and confirm failures are missing lifecycle mappings.
- [x] Add fixed lifecycle `ActionSpec`s and include them in `help_text()` without changing plugin task actions.
- [x] Re-run `pytest tests/test_command_registry.py -q`.

### Task 2: Add authenticated GUI close action

**Files:**
- Modify: `feishu_plugin_sdk/remote_control.py`
- Test: `tests/test_remote_control.py`

- [x] Add failing tests showing `shutdown` is dispatched only when idle and refused when `busy` is true.
- [x] Run `pytest tests/test_remote_control.py -q` and verify the expected unsupported-action/busy failures.
- [x] Extend the existing queue protocol with a distinct shutdown action and a clear busy refusal.
- [x] Re-run `pytest tests/test_remote_control.py -q`.

### Task 3: Start and close registered GUI applications

**Files:**
- Modify: `feishu_bot.py`, `controller_client.py`
- Create: `application_lifecycle.py`
- Test: `tests/test_controller_service.py`, `tests/test_controller_client.py`, `tests/test_application_lifecycle.py`

- [x] Add failing tests for launch idempotency, missing launcher, readiness timeout, lifecycle close routing, and busy refusal.
- [x] Run the focused tests and verify they fail because lifecycle management is absent.
- [x] Implement fixed launch specifications for analyzer, downloader, and LVR, using configured roots and known entrypoints only.
- [x] Add authenticated client support for the distinct GUI shutdown action.
- [x] Route lifecycle `ActionSpec`s through the lifecycle manager while preserving task command dispatch.
- [x] Re-run focused controller tests.

### Task 4: Handle GUI shutdown in each application

**Files:**
- Modify: `D:/pycharm_pro/bilibili-hiatus-analyzer/backend/remote_control.py`
- Modify: `D:/pycharm_pro/bilibili-hiatus-analyzer/gui.py`
- Modify: `D:/pycharm_pro/bilibili-hiatus-analyzer/douyin-downloader-main/gui.py`
- Modify: `D:/pycharm_pro/Local-Video-Renamer/code/app/gui/main_window.py`
- Test: each repository's existing remote-control or startup tests

- [x] Add failing tests for idle close dispatch, busy close refusal, and GUI-thread event-loop scheduling.
- [x] Run each focused test and confirm it fails for the missing shutdown action.
- [x] In each GUI command handler, delegate to the existing normal close path on its GUI thread.
- [x] Re-run the analyzer, downloader, and LVR focused tests.

### Task 5: Manage Quark Web process lifecycle

**Files:**
- Modify: `application_lifecycle.py`, `.env.example`
- Test: `tests/test_application_lifecycle.py`
- Test: `D:/pycharm_pro/Quark-File-Management/tests/test_control_server.py` or a focused new lifecycle test module

- [x] Add failing tests for Quark Web launch, controller-owned graceful stop, and refusal to stop an unmanaged server.
- [x] Verify the failures are due to absent process ownership behavior.
- [x] Launch the known `start_web.bat` entrypoint in a tracked process group and wait for its configured HTTP endpoint.
- [x] Request a graceful console shutdown only for the tracked process; keep an unmanaged healthy server untouched.
- [x] Re-run controller and Quark lifecycle tests.

### Task 6: Finish command responses and documentation

**Files:**
- Modify: `feishu_bot.py`, `docs/CONTROL_PROTOCOL.md`, `README.md`, `.env.example`
- Test: `tests/test_feishu_bot.py`, `tests/test_end_to_end_control.py`

- [x] Add failing tests for command dispatch, help text, already-running response, busy close response, and lifecycle request idempotency.
- [x] Run focused tests and verify the expected missing command behavior.
- [x] Add final response wording and document lifecycle versus task control semantics.
- [x] Re-run controller tests and protocol end-to-end tests.

### Task 7: Verify all four repositories

**Files:** No production files unless a test exposes a defect.

- [x] Run controller focused and full test suites.
- [x] Run analyzer remote-control tests.
- [x] Run downloader remote-control tests.
- [x] Run LVR startup/control tests.
- [x] Run Quark control-service tests and inspect its `start_web.bat` launcher.
- [x] Review each repository's status to ensure pre-existing user changes remain intact.

Verification note: the controller suite has one known baseline failure in `test_manifest_discovery_registers_healthy_plugin_and_isolates_offline_one`; offline plugins currently remain registered as status-only entries. The remaining 123 tests pass. No GUI or application process was launched during verification.
