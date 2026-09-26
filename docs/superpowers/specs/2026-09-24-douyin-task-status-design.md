# Douyin Task Status Design

The downloader status endpoint must identify active GUI-launched work as well as work started through Feishu. While busy, it will publish the active audit run ID as `task_id` and a user-facing task label derived from the run kind as `task_title`. Every worker that can make the GUI busy must have a run kind, including statistics refresh. When idle, task fields must be cleared. Existing historical `running` audit rows will not be rewritten because ownership cannot be proven safely.

Verification will cover task metadata while busy, clearing it once idle, and assigning a run kind to statistics refresh. Existing stop behavior and audit history remain unchanged.
