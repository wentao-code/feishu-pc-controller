"""Feishu bot for receiving owner-only status and shutdown commands."""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlparse
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from dotenv import load_dotenv

from command_registry import ActionSpec, CommandRegistry, normalize_command
from controller_client import ControlClient, ControlClientError
from controller_api import ControllerApi
from feishu_plugin_sdk.manifest import PluginManifest
from manifest_client import ManifestClient, ManifestClientError
from notifier import Notifier
from plugin_registry import PluginAction, PluginRegistry, PluginSpec, legacy_plugin_specs
from report_store import ReportStore
from task_protocol import CommandResponse

load_dotenv()  # Load values from the local .env file when present.

LOGGER = logging.getLogger(__name__)

SHUTDOWN_DELAY_SECONDS = 15
STARTUP_MESSAGE = "通知助手开始工作"
_shutdown_timer: threading.Timer | None = None
_shutdown_lock = threading.Lock()


@dataclass(frozen=True)
class BotConfig:
    app_id: str
    app_secret: str
    owner_open_id: str
    control_token: str = ""
    main_analyzer_url: str = "http://127.0.0.1:8761"
    downloader_url: str = "http://127.0.0.1:8762"
    controller_host: str = "127.0.0.1"
    controller_port: int = 8760
    report_database_path: str = "runtime/controller-reports.db"
    control_timeout: float = 5.0
    plugins: tuple[PluginSpec, ...] = ()
    plugins_configured: bool = False


@dataclass(frozen=True)
class PluginEndpoint:
    plugin_id: str
    base_url: str
    required_ready_fields: tuple[str, ...] = ("ready",)
    required_status_values: Mapping[str, tuple[object, ...]] = field(default_factory=dict)
    refusal_messages: Mapping[str, str] = field(default_factory=dict)
    status_messages: Mapping[str, str] = field(default_factory=dict)
    action_namespace: str | None = None

    def __post_init__(self) -> None:
        plugin_id = str(self.plugin_id or "").strip()
        base_url = str(self.base_url or "").strip().rstrip("/")
        if not plugin_id:
            raise ValueError("plugin endpoint id is required")
        if not base_url:
            raise ValueError("plugin endpoint url is required")
        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or parsed_url.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("plugin endpoint url must use a loopback host")
        object.__setattr__(self, "plugin_id", plugin_id)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(
            self,
            "required_ready_fields",
            tuple(str(value).strip() for value in self.required_ready_fields if str(value).strip()),
        )
        object.__setattr__(
            self,
            "required_status_values",
            {str(key): tuple(values) for key, values in self.required_status_values.items()},
        )
        object.__setattr__(
            self,
            "refusal_messages",
            {str(key): str(value) for key, value in self.refusal_messages.items()},
        )
        object.__setattr__(
            self,
            "status_messages",
            {str(key): str(value) for key, value in self.status_messages.items()},
        )

    def policy(self) -> dict[str, object]:
        return {
            "required_ready_fields": self.required_ready_fields,
            "required_status_values": self.required_status_values,
            "refusal_messages": self.refusal_messages,
            "status_messages": self.status_messages,
            "action_namespace": self.action_namespace,
        }


def load_plugin_endpoints(raw: str) -> tuple[PluginEndpoint, ...]:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("FEISHU_PLUGIN_ENDPOINTS_JSON must be valid JSON") from error
    if not isinstance(payload, list):
        raise ValueError("FEISHU_PLUGIN_ENDPOINTS_JSON must be a JSON array")

    endpoints: list[PluginEndpoint] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, Mapping):
            raise ValueError("plugin endpoint must be an object")
        plugin_id = str(item.get("id") or item.get("plugin_id") or "").strip()
        base_url = str(item.get("url") or item.get("base_url") or "").strip()
        if not plugin_id:
            raise ValueError("plugin endpoint id is required")
        if not base_url:
            raise ValueError("plugin endpoint url is required")
        if plugin_id in seen:
            raise ValueError(f"duplicate plugin endpoint: {plugin_id}")
        seen.add(plugin_id)

        required_values = item.get("required_status_values") or {}
        if not isinstance(required_values, Mapping):
            raise ValueError("plugin endpoint required_status_values must be an object")
        endpoints.append(
            PluginEndpoint(
                plugin_id=plugin_id,
                base_url=base_url,
                required_ready_fields=tuple(
                    item.get("required_ready_fields") or ("ready",)
                ),
                required_status_values={
                    str(key): tuple(value) if isinstance(value, (list, tuple)) else (value,)
                    for key, value in required_values.items()
                },
                refusal_messages=dict(item.get("refusal_messages") or {}),
                status_messages=dict(item.get("status_messages") or {}),
                action_namespace=item.get("action_namespace"),
            )
        )
    return tuple(endpoints)


def discover_plugins(
    endpoints: tuple[PluginEndpoint, ...],
    control_token: str,
    *,
    timeout: float,
) -> tuple[PluginSpec, ...]:
    discovered: list[PluginSpec] = []
    for endpoint in endpoints:
        try:
            manifest = ManifestClient(
                endpoint.base_url,
                control_token,
                timeout=timeout,
            ).fetch()
            if manifest.plugin_id != endpoint.plugin_id:
                raise ValueError(
                    f"Manifest plugin_id {manifest.plugin_id!r} does not match "
                    f"configured id {endpoint.plugin_id!r}"
                )
            policy = endpoint.policy()
            if manifest.integration.get("bound") is False:
                required_status_values = dict(policy["required_status_values"])
                required_status_values.setdefault("control_bound", (True,))
                policy["required_status_values"] = required_status_values
                integration_message = str(
                    manifest.integration.get("message")
                    or f"{manifest.label}尚未绑定业务入口"
                )
                refusal_messages = dict(policy["refusal_messages"])
                refusal_messages.setdefault("control_bound", integration_message)
                policy["refusal_messages"] = refusal_messages
                status_messages = dict(policy["status_messages"])
                status_messages.setdefault("control_bound", integration_message)
                policy["status_messages"] = status_messages
            discovered.append(
                PluginSpec.from_manifest(manifest, endpoint.base_url, **policy)
            )
        except (ManifestClientError, TypeError, ValueError) as error:
            LOGGER.warning("[插件发现失败] %s: %s", endpoint.plugin_id, error)
            label = endpoint.plugin_id.replace("_", " ").title()
            discovered.append(
                PluginSpec(
                    plugin_id=endpoint.plugin_id,
                    label=label,
                    base_url=endpoint.base_url,
                    actions=(
                        PluginAction(
                            "status",
                            "查看状态",
                            (f"{label}：状态", f"{endpoint.plugin_id} status"),
                        ),
                    ),
                    action_namespace=endpoint.action_namespace,
                )
            )
    return tuple(discovered)


def load_config(environ: Mapping[str, str] | None = None) -> BotConfig:
    """Load and validate Feishu credentials from environment variables."""
    values = os.environ if environ is None else environ
    names = (
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_OWNER_OPEN_ID",
        "FEISHU_CONTROL_TOKEN",
    )
    missing = [name for name in names if not values.get(name, "").strip()]
    if missing:
        raise ValueError(
            "缺少必需的环境变量: "
            + ", ".join(missing)
            + "。请在 .env 或系统环境变量中配置。"
        )

    raw_endpoints = values.get("FEISHU_PLUGIN_ENDPOINTS_JSON", "").strip()
    raw_plugins = values.get("FEISHU_PLUGINS_JSON", "").strip()
    plugins: tuple[PluginSpec, ...] = ()
    plugins_configured = False
    if raw_endpoints:
        endpoints = load_plugin_endpoints(raw_endpoints)
        discovered_plugins = discover_plugins(
            endpoints,
            values["FEISHU_CONTROL_TOKEN"].strip(),
            timeout=float(values.get("FEISHU_CONTROL_TIMEOUT", "5")),
        )
        legacy_plugins = legacy_plugin_specs(
            values.get("FEISHU_MAIN_ANALYZER_URL", "http://127.0.0.1:8761").strip(),
            values.get("FEISHU_DOUYIN_DOWNLOADER_URL", "http://127.0.0.1:8762").strip(),
        )
        discovered_by_id = {plugin.plugin_id: plugin for plugin in discovered_plugins}
        plugins = tuple(
            discovered_by_id.pop(plugin.plugin_id, plugin) for plugin in legacy_plugins
        ) + tuple(discovered_by_id.values())
        plugins_configured = True
    elif raw_plugins:
        try:
            plugins = tuple(PluginRegistry.from_json(raw_plugins))
        except ValueError as error:
            raise ValueError(str(error)) from error
        plugins_configured = True

    return BotConfig(
        app_id=values["FEISHU_APP_ID"].strip(),
        app_secret=values["FEISHU_APP_SECRET"].strip(),
        owner_open_id=values["FEISHU_OWNER_OPEN_ID"].strip(),
        control_token=values.get("FEISHU_CONTROL_TOKEN", "").strip(),
        main_analyzer_url=values.get(
            "FEISHU_MAIN_ANALYZER_URL", "http://127.0.0.1:8761"
        ).strip(),
        downloader_url=values.get(
            "FEISHU_DOUYIN_DOWNLOADER_URL", "http://127.0.0.1:8762"
        ).strip(),
        controller_host=values.get("FEISHU_CONTROLLER_HOST", "127.0.0.1").strip(),
        controller_port=int(values.get("FEISHU_CONTROLLER_PORT", "8760")),
        report_database_path=values.get(
            "FEISHU_REPORT_DATABASE_PATH", "runtime/controller-reports.db"
        ).strip(),
        control_timeout=float(values.get("FEISHU_CONTROL_TIMEOUT", "5")),
        plugins=plugins,
        plugins_configured=plugins_configured,
    )


def command_for_message(text: str) -> str:
    """Normalize a message into a supported command name."""
    normalized = text.strip().lower()
    if normalized in {"关机", "shutdown", "关闭电脑"}:
        return "shutdown"
    if normalized in {"取消关机", "cancel", "cancel shutdown"}:
        return "cancel_shutdown"
    if normalized in {"指令集合", "帮助", "help", "commands"}:
        return "help"
    if normalized in {"状态", "status"}:
        return "status"
    action = normalize_command(text)
    command_names = {
        "douyin.fetch.start": "douyin_fetch_start",
        "douyin.fetch.stop": "douyin_fetch_stop",
        "douyin.fetch.status": "douyin_fetch_status",
        "douyin.download.start": "douyin_download_start",
        "douyin.download.stop": "douyin_download_stop",
        "douyin.download.status": "douyin_download_status",
    }
    if action in command_names:
        return command_names[action]
    return "echo"


def command_help_text(registry: CommandRegistry | None = None) -> str:
    """Return the available commands and their expected replies."""
    lines = [
        "可用指令：\n"
        "1. 状态 / status：查看所有已接入系统的运行状态\n"
        "2. 关机 / shutdown / 关闭电脑：回复“收到关机指令，15秒后关机。”\n"
        "3. 取消关机 / cancel / cancel shutdown：回复“已取消关机任务。”\n"
        "4. 指令集合 / 帮助 / help / commands：显示本指令列表\n"
    ]
    dynamic = (registry or CommandRegistry()).help_text().splitlines()[1:]
    lines.extend(f"{index}. {line}" for index, line in enumerate(dynamic, start=5))
    lines.append("未知或无效指令：回复完整指令集，不执行任何操作")
    return "\n".join(lines)


def create_feishu_client(config: BotConfig):
    """Build the Feishu API client only after configuration is validated."""
    import lark_oapi as lark

    return (
        lark.Client.builder()
        .app_id(config.app_id)
        .app_secret(config.app_secret)
        .build()
    )


def send_message_to_owner(
    text: str,
    config: BotConfig,
    client=None,
) -> None:
    """Send a text message to the configured owner."""
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    client = client or create_feishu_client(config)
    request = (
        CreateMessageRequest.builder()
        .receive_id_type("open_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(config.owner_open_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        .build()
    )

    response = client.im.v1.message.create(request)
    if response.success():
        print(f"[发送成功] 消息ID: {response.data.message_id}")
    else:
        print(f"[发送失败] code: {response.code}, msg: {response.msg}")


def send_startup_notification(config: BotConfig, client) -> None:
    """Notify the owner that this bot process has started."""
    try:
        send_message_to_owner(STARTUP_MESSAGE, config, client)
    except Exception as error:
        print(f"[启动通知失败] {error}")


def _execute_shutdown() -> None:
    """Execute the shutdown after the cancellation window expires."""
    global _shutdown_timer
    try:
        if os.name == "nt":
            subprocess.run(["shutdown", "/s", "/t", "0"], check=False)
        else:
            subprocess.run(["shutdown", "-h", "now"], check=False)
    finally:
        with _shutdown_lock:
            _shutdown_timer = None


def handle_shutdown() -> None:
    """Schedule a shutdown fifteen seconds from now."""
    global _shutdown_timer
    with _shutdown_lock:
        if _shutdown_timer is not None:
            print("[忽略] 已存在待执行的关机任务")
            return
        _shutdown_timer = threading.Timer(
            SHUTDOWN_DELAY_SECONDS,
            _execute_shutdown,
        )
        _shutdown_timer.daemon = True
        _shutdown_timer.start()
    print("[执行关机] 收到关机指令，15秒后关机...")


def cancel_shutdown() -> bool:
    """Cancel the pending shutdown, returning whether one existed."""
    global _shutdown_timer
    with _shutdown_lock:
        timer = _shutdown_timer
        _shutdown_timer = None

    if timer is None:
        print("[取消关机] 当前没有待执行的关机任务")
        return False

    timer.cancel()
    print("[取消关机] 已取消关机任务")
    return True


class ControllerService:
    """Dispatch approved Feishu actions to the two local GUI adapters."""

    def __init__(
        self,
        config: BotConfig,
        *,
        clients: Mapping[str, ControlClient] | None = None,
    ) -> None:
        self.config = config
        plugin_specs = (
            config.plugins
            if config.plugins_configured
            else config.plugins
            or legacy_plugin_specs(config.main_analyzer_url, config.downloader_url)
        )
        self.registry = CommandRegistry(PluginRegistry(plugin_specs))
        self._request_cache: dict[str, CommandResponse] = {}
        self._request_inflight: dict[str, threading.Event] = {}
        self._request_cache_lock = threading.RLock()
        self.clients = dict(
            clients
            or {
                plugin.plugin_id: ControlClient(
                    plugin.base_url,
                    config.control_token,
                    timeout=config.control_timeout,
                )
                for plugin in self.registry.plugins
            }
        )

    def handle_action(self, target: ActionSpec | None, request_id: str) -> CommandResponse:
        with self._request_cache_lock:
            cached = self._request_cache.get(request_id)
            if cached is not None:
                return cached
            inflight = self._request_inflight.get(request_id)
            if inflight is None:
                inflight = threading.Event()
                self._request_inflight[request_id] = inflight
                owner = True
            else:
                owner = False

        if not owner:
            inflight.wait()
            with self._request_cache_lock:
                return self._request_cache[request_id]

        try:
            if target is None:
                response = self._rejected(request_id, "不支持的指令")
            elif target.action == "system.status":
                response = self._status_response(request_id)
            else:
                client = self.clients.get(target.target)
                if client is None:
                    response = self._rejected(request_id, "目标程序未配置")
                else:
                    try:
                        status = client.get_status(target)
                        if target.target_action == "status":
                            response = self._plugin_status_response(target, request_id, status)
                        else:
                            reason = self._refusal_reason(target, status)
                            if reason:
                                response = self._rejected(request_id, reason)
                            elif target.target_action == "stop":
                                response = client.stop(target, request_id)
                            else:
                                response = client.start(target, request_id)
                    except ControlClientError as error:
                        reason = "系统未启动" if error.system_not_started else str(error)
                        response = self._rejected(request_id, reason)
        except Exception as error:
            response = self._rejected(request_id, f"控制服务异常：{error}")
        finally:
            with self._request_cache_lock:
                self._request_cache[request_id] = response
                waiter = self._request_inflight.pop(request_id)
                waiter.set()
        return response

    def status_text(self, plugin_id: str | None = None) -> str:
        lines = ["系统状态："]
        plugins = tuple(
            plugin
            for plugin in self.registry.plugins
            if plugin_id is None or plugin.plugin_id == plugin_id
        )
        if plugin_id is not None and not plugins:
            return f"{plugin_id}：未配置"
        for plugin in plugins:
            target_name = plugin.plugin_id
            label = plugin.label
            target = ActionSpec("system.status", target_name, "status", label)
            client = self.clients.get(plugin.plugin_id)
            if client is None:
                lines.append(f"{label}：未配置")
                continue
            try:
                status = client.get_status(target)
            except ControlClientError as error:
                if error.system_not_started:
                    lines.append(f"{label}：系统未启动")
                else:
                    lines.append(f"{label}：不可用（{error}）")
                continue
            lines.append(self._format_plugin_status(plugin, status))
        if plugin_id is not None:
            return lines[1]
        return "\n".join(lines)

    @staticmethod
    def _format_plugin_status(plugin: PluginSpec, status: Mapping[str, object]) -> str:
        label = plugin.label
        if not status.get("gui_running"):
            return f"{label}：未运行"
        if status.get("task_status_known") is False:
            return f"{label}：任务状态未知，尚未接入 GUI 任务队列"
        if status.get("busy"):
            task_title = str(status.get("task_title") or "").strip()
            task_label = task_title or str(status.get("task_id") or "未知")
            message = f"{label}：运行中，当前任务：{task_label}"
            try:
                queue_depth = max(0, int(status.get("queue_depth") or 0))
            except (TypeError, ValueError):
                queue_depth = 0
            if queue_depth:
                message += f"，另有 {queue_depth} 项排队"
            return message
        try:
            queue_depth = max(0, int(status.get("queue_depth") or 0))
        except (TypeError, ValueError):
            queue_depth = 0
        if queue_depth:
            return f"{label}：当前无任务执行，另有 {queue_depth} 项等待处理"
        return f"{label}：已启动，当前空闲"

    def _plugin_status_response(
        self,
        target: ActionSpec,
        request_id: str,
        status: Mapping[str, object] | None = None,
    ) -> CommandResponse:
        plugin = self.registry.plugins.get(target.target)
        client = self.clients.get(target.target)
        if plugin is None or client is None:
            return self._rejected(request_id, "目标程序未配置")
        if status is None:
            try:
                status = client.get_status(target)
            except ControlClientError as error:
                return self._rejected(request_id, f"{plugin.label}状态异常：{error}")
        return CommandResponse(
            request_id=request_id,
            accepted=True,
            status="accepted",
            message=self._format_plugin_status(plugin, status),
        )

    def _refusal_reason(self, target: ActionSpec, status: Mapping[str, object]) -> str | None:
        plugin = self.registry.plugins.get(target.target)
        if plugin is None:
            return "目标程序未配置"
        if not status.get("gui_running"):
            return plugin.refusal_messages.get("gui_running", f"{plugin.label}未运行")
        if target.target_action == "status":
            return None
        if target.target_action == "stop":
            if not status.get("busy"):
                return "当前没有正在运行的任务，无需停止。"
            return None
        if status.get("busy"):
            return plugin.refusal_messages.get("busy", f"{plugin.label}当前已有任务运行中")
        for field in plugin.required_ready_fields:
            if not status.get(field):
                return plugin.refusal_messages.get(field, f"当前状态不满足：{field}")
        for field, allowed_values in plugin.required_status_values.items():
            if status.get(field) not in allowed_values:
                return plugin.refusal_messages.get(field, f"当前状态不支持：{field}")
        return None

    @staticmethod
    def _rejected(request_id: str, reason: str):
        return CommandResponse(
            request_id=request_id,
            accepted=False,
            status="rejected",
            reason=reason,
        )

    @staticmethod
    def _status_response(request_id: str):
        return CommandResponse(
            request_id=request_id,
            accepted=True,
            status="accepted",
            message="状态查询请使用 status_text()",
        )


def on_message_receive(
    data,
    config: BotConfig,
    client=None,
    shutdown_runner: Callable[[], None] = handle_shutdown,
    controller_service: ControllerService | None = None,
) -> None:
    """Handle one Feishu message event."""
    try:
        message = data.event.message
        msg_type = message.message_type
        if msg_type == "text":
            content = json.loads(message.content)
            text = content.get("text", "").strip()
        else:
            text = f"[非文本消息: {msg_type}]"

        sender_open_id = data.event.sender.sender_id.open_id
        print(f"[收到消息] 来自 {sender_open_id}: {text}")

        if sender_open_id != config.owner_open_id:
            print("[忽略] 非 owner 发来的消息")
            return

        command = command_for_message(text)
        if command == "help":
            registry = controller_service.registry if controller_service is not None else None
            send_message_to_owner(command_help_text(registry), config, client)
        elif command == "shutdown":
            send_message_to_owner("收到关机指令，15秒后关机。", config, client)
            shutdown_runner()
        elif command == "cancel_shutdown":
            if cancel_shutdown():
                send_message_to_owner("已取消关机任务。", config, client)
            else:
                send_message_to_owner("当前没有待执行的关机任务。", config, client)
        elif command == "status":
            if controller_service is None:
                send_message_to_owner("机器人运行正常。", config, client)
            else:
                send_message_to_owner(controller_service.status_text(), config, client)
        elif command in {
            "douyin_fetch_start",
            "douyin_fetch_stop",
            "douyin_download_start",
            "douyin_download_stop",
        }:
            if controller_service is None:
                send_message_to_owner("控制服务尚未初始化，无法执行任务。", config, client)
                return
            action_text = {
                "douyin_fetch_start": "抖音：开始运行",
                "douyin_fetch_stop": "抖音：停止运行",
                "douyin_download_start": "抖音：开始下载",
                "douyin_download_stop": "抖音：停止下载",
            }[command]
            target = controller_service.registry.resolve(action_text)
            request_id = str(
                getattr(data, "event_id", None)
                or getattr(getattr(data, "event", None), "event_id", None)
                or uuid.uuid4().hex
            )
            response = controller_service.handle_action(target, request_id)
            if getattr(response, "accepted", False) and target.target_action == "stop":
                send_message_to_owner(
                    "停止请求已提交，当前处理完成后会安全停止。",
                    config,
                    client,
                )
            elif getattr(response, "accepted", False):
                send_message_to_owner(
                    f"已接受{action_text}，正在按当前配置启动。任务 ID：{getattr(response, 'task_id', None) or '启动中'}",
                    config,
                    client,
                )
            else:
                send_message_to_owner(
                    f"{action_text}已拒绝：{getattr(response, 'reason', None) or '未知原因'}",
                    config,
                    client,
                )
        else:
            target = controller_service.registry.resolve(text) if controller_service else None
            if controller_service is None:
                send_message_to_owner(command_help_text(), config, client)
            elif target is None:
                send_message_to_owner(
                    command_help_text(controller_service.registry),
                    config,
                    client,
                )
            elif target.action == "system.status":
                send_message_to_owner(f"收到指令：{text}", config, client)
            else:
                request_id = str(
                    getattr(data, "event_id", None)
                    or getattr(getattr(data, "event", None), "event_id", None)
                    or uuid.uuid4().hex
                )
                response = controller_service.handle_action(target, request_id)
                if response.accepted and target.target_action == "status":
                    message = response.message
                elif response.accepted and target.target_action == "stop":
                    message = "停止请求已提交，当前处理完成后会安全停止。"
                elif response.accepted:
                    message = (
                        f"已接受{target.label}，正在按当前配置启动。"
                        f"任务 ID：{response.task_id or '启动中'}"
                    )
                else:
                    message = f"{target.label}已拒绝：{response.reason or '未知原因'}"
                send_message_to_owner(message, config, client)
    except Exception as error:
        print(f"[处理消息出错] {error}")


def main() -> None:
    import lark_oapi as lark

    config = load_config()
    client = create_feishu_client(config)
    report_path = Path(config.report_database_path)
    if not report_path.is_absolute():
        report_path = Path(__file__).resolve().parent / report_path
    report_store = ReportStore(report_path)
    notifier = Notifier(lambda message: send_message_to_owner(message, config, client))
    controller_api = None
    if config.control_token:
        controller_api = ControllerApi(
            report_store,
            token=config.control_token,
            host=config.controller_host,
            port=config.controller_port,
            on_report=notifier.notify_report,
        )
        controller_api.start_in_thread()
        print(f"[启动] 控制接口已监听 {controller_api.base_url}")
    else:
        print("[警告] 未配置 FEISHU_CONTROL_TOKEN，远程控制和任务汇报接口未启动")
    controller_service = ControllerService(config)
    send_startup_notification(config, client)
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(
            lambda data: on_message_receive(
                data,
                config,
                client,
                controller_service=controller_service,
            )
        )
        .build()
    )
    ws_client = lark.ws.Client(
        config.app_id,
        config.app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG,
    )

    print("[启动] 飞书机器人长连接已建立，等待消息...")
    try:
        ws_client.start()
    finally:
        if controller_api is not None:
            controller_api.stop()
        report_store.close()


if __name__ == "__main__":
    main()
