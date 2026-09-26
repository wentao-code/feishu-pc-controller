# Douyin Task Status Implementation Plan

> **For agentic workers:** Implement inline in this session using test-driven development.

**Goal:** Make Feishu status identify active tasks started from the downloader GUI.

**Architecture:** The downloader GUI already owns the active audit run ID and run kind. Its existing status snapshot will expose those values as `task_id` and `task_title`; Feishu's current formatter already displays them. Historical audit records are left untouched.

**Tech Stack:** Python, pytest, shared `StatusSnapshot` SDK.

## Global Constraints

- Do not alter existing audit history or stop behavior.
- Preserve unrelated working-tree changes.

---

### Task 1: Report active downloader task metadata

**Files:**
- Modify: `D:/pycharm_pro/bilibili-hiatus-analyzer/douyin-downloader-main/gui.py`
- Test: `D:/pycharm_pro/bilibili-hiatus-analyzer/douyin-downloader-main/tests/test_remote_control.py`

- [x] Add a failing test proving `_sync_remote_status()` includes the active audit run ID and a readable title while busy.
- [x] Run that test and confirm it fails because the status snapshot omits those fields.
- [x] Add labels for downloader run kinds, include `douyin_stats_refresh` for refresh work, and sync task metadata from the active run into `StatusSnapshot`.
- [x] Add assertions that idle status clears task identity and refresh starts an auditable, named run.
- [x] Run the remote-control test module and the downloader's relevant GUI/task tests.

### Task 2: Verify integration and preserve scope

**Files:**
- Verify: both files above and the Feishu status formatter.

- [x] Run the complete downloader test suite if runtime permits.
- [x] Confirm Feishu's existing formatter displays the newly reported `task_title` and does not require code changes.
- [x] Inspect diffs and verify no historical audit rows or unrelated files changed.
