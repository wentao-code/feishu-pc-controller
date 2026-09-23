# Manifest-Driven Plugin Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the controller consume explicit plugin endpoints, fetch and validate each plugin Manifest, and build its dynamic registry without breaking legacy configuration.

**Architecture:** Add an authenticated standard-library Manifest client and a conversion boundary from the shared `PluginManifest` model to the controller's `PluginSpec`. `load_config` will select endpoint discovery, static JSON, or legacy built-ins in that order; endpoint failures are isolated per plugin and reported through startup diagnostics.

**Tech Stack:** Python 3.10+, standard-library `urllib.request`, existing dataclasses, pytest, shared `feishu_plugin_sdk`.

## Global Constraints

- Endpoint discovery is explicit; never scan arbitrary hosts or ports.
- All plugin HTTP requests use `Authorization: Bearer <FEISHU_CONTROL_TOKEN>`.
- Manifest action names are limited to `start` and `stop`; labels and aliases come from the Manifest.
- Existing `FEISHU_PLUGINS_JSON` and legacy analyzer/downloader startup remain compatible when the new endpoint variable is absent.
- A failed plugin is isolated and cannot prevent healthy plugins from registering.
- Do not bind new GUI buttons or duplicate business logic.

### Task 1: Add the authenticated Manifest client

**Files:**
- Create: `manifest_client.py`
- Create: `tests/test_manifest_client.py`

**Interfaces:**
- `ManifestClient(base_url: str, token: str, timeout: float = 5.0, opener=urllib.request.urlopen)`
- `ManifestClient.fetch() -> PluginManifest`
- `ManifestClientError` with optional `status_code`

- [x] Write tests for bearer authentication, valid conversion, timeout/URL failure, HTTP error detail, and invalid Manifest payload.
- [x] Run `python -m pytest -q tests/test_manifest_client.py` and confirm it fails because the module is absent.
- [x] Implement the client with the same error mapping style as `ControlClient`; call only `/api/v1/manifest`.
- [x] Run the focused tests and confirm they pass.

### Task 2: Convert Manifest capabilities into registry specs

**Files:**
- Modify: `plugin_registry.py`
- Modify: `tests/test_plugin_registry.py`

**Interfaces:**
- `PluginSpec.from_manifest(manifest: PluginManifest, base_url: str, **policy_overrides) -> PluginSpec`
- `PluginRegistry.from_manifests(entries: Iterable[tuple[PluginManifest, str, Mapping[str, Any]]]) -> PluginRegistry`

- [x] Write tests proving Manifest labels/aliases become `PluginAction` values and policy overrides remain separate from public capabilities.
- [x] Run the focused registry tests and confirm the new tests fail.
- [x] Implement the conversion methods with duplicate ID/alias validation delegated to existing registry invariants.
- [x] Run `python -m pytest -q tests/test_plugin_registry.py` and confirm all tests pass.

### Task 3: Add explicit endpoint discovery to configuration

**Files:**
- Modify: `feishu_bot.py`
- Modify: `tests/test_feishu_bot.py`
- Modify: `.env.example`

**Interfaces:**
- `PluginEndpoint` immutable configuration record with `plugin_id`, `base_url`, and policy mappings.
- `load_plugin_endpoints(raw: str) -> tuple[PluginEndpoint, ...]`
- `discover_plugins(endpoints, control_token, timeout) -> tuple[PluginSpec, ...]`

- [x] Write tests for endpoint JSON parsing, missing IDs/URLs, successful discovery, and isolation of one offline endpoint.
- [x] Run the focused tests and confirm they fail because endpoint discovery is absent.
- [x] Implement endpoint parsing and discovery; collect diagnostics without exposing tokens.
- [x] Make `load_config` prefer `FEISHU_PLUGIN_ENDPOINTS_JSON`, otherwise preserve static JSON, otherwise preserve legacy entries.
- [x] Run `python -m pytest -q tests/test_feishu_bot.py tests/test_manifest_client.py tests/test_plugin_registry.py`.

### Task 4: Add end-to-end discovered-plugin coverage and documentation

**Files:**
- Modify: `tests/test_end_to_end_control.py`
- Modify: `README.md`
- Modify: `docs/CONTROL_PROTOCOL.md`

- [x] Add a fake authenticated plugin endpoint that serves a Manifest and status, accepts a command, and verify `ControllerService` routes a command through the discovered `PluginSpec`.
- [x] Add an offline endpoint beside a healthy endpoint and verify only the healthy plugin appears in the registry.
- [x] Document `FEISHU_PLUGIN_ENDPOINTS_JSON`, precedence, and failure isolation.
- [x] Run the complete controller suite and then the existing Local Video Renamer and Quark focused tests.

### Task 5: Final verification

- [x] Run `git diff --check` in all three repositories.
- [x] Run `python -m py_compile` for all new and modified controller Python files.
- [x] Run complete pytest suites in `feishu-pc-controller`, `Local-Video-Renamer/code`, and `Quark-File-Management`.
- [x] Confirm `.env`, runtime databases, logs, browser profiles, and caches are not staged or newly tracked.
