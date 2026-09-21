"""Feishu bot for receiving owner-only status and shutdown commands."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from dotenv import load_dotenv

from command_registry import ActionSpec, CommandRegistry, normalize_command
from controller_client import ControlClient, ControlClientError
from controller_api import ControllerApi
from notifier import Notifier
from report_store import ReportStore
from task_protocol import CommandResponse

load_dotenv()  # Load values from the local .env file when present.

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


def load_config(environ: Mapping[str, str] | None = None) -> BotConfig:
    """Load and validate Feishu credentials from environment variables."""
    values = os.environ if environ is None else environ
    names = (
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_OWNER_OPEN_ID",
    )
    missing = [name for name in names if not values.get(name, "").strip()]
    if missing:
        raise ValueError(
            "缺少必需的环境变量: "
            + ", ".join(missing)
            + "。请在 .env 或系统环境变量中配置。"
        )

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
    if action == "douyin.fetch.start":
        return "douyin_fetch_start"
    if action == "douyin.download.start":
        return "douyin_download_start"
    return "echo"


def command_help_text() -> str:
    """Return the available commands and their expected replies."""
    return (
        "可用指令：\n"
        "1. 状态 / status：回复“机器人运行正常。”\n"
        "2. 关机 / shutdown / 关闭电脑：回复“收到关机指令，15秒后关机。”\n"
        "3. 取消关机 / cancel / cancel shutdown：回复“已取消关机任务。”\n"
        "4. 指令集合 / 帮助 / help / commands：显示本指令列表\n"
        "5. 抖音：开始运行：按主程序锁定配置开始抓取\n"
        "6. 抖音：开始下载：按下载器当前设置开始下载\n"
        "7. 其他文本：原样回复“收到指令：你的内容”"
    )


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
        self.registry = CommandRegistry()
        self._request_cache: dict[str, CommandResponse] = {}
        self._request_cache_lock = threading.RLock()
        self.clients = dict(clients or {
            "main_analyzer": ControlClient(
                config.main_analyzer_url,
                config.control_token,
                timeout=config.control_timeout,
            ),
            "douyin_downloader": ControlClient(
                config.downloader_url,
                config.control_token,
                timeout=config.control_timeout,
            ),
        })

    def handle_action(self, target: ActionSpec | None, request_id: str) -> CommandResponse:
        with self._request_cache_lock:
            cached = self._request_cache.get(request_id)
        if cached is not None:
            return cached

        def finish(response: CommandResponse) -> CommandResponse:
            with self._request_cache_lock:
                self._request_cache[request_id] = response
            return response

        if target is None:
            return finish(self._rejected(request_id, "不支持的指令"))
        if target.action == "system.status":
            return finish(self._status_response(request_id))

        client = self.clients.get(target.target)
        if client is None:
            return finish(self._rejected(request_id, "目标程序未配置"))
        try:
            status = client.get_status(target)
        except ControlClientError as error:
            return finish(self._rejected(request_id, str(error)))
        reason = self._refusal_reason(target, status)
        if reason:
            return finish(self._rejected(request_id, reason))
        try:
            return finish(client.start(target, request_id))
        except ControlClientError as error:
            return finish(self._rejected(request_id, str(error)))

    def status_text(self) -> str:
        lines = ["系统状态："]
        for target_name, label in (
            ("main_analyzer", "主程序"),
            ("douyin_downloader", "抖音下载程序"),
        ):
            target = ActionSpec("system.status", target_name, "status", label)
            client = self.clients.get(target_name)
            if client is None:
                lines.append(f"{label}：未配置")
                continue
            try:
                status = client.get_status(target)
            except ControlClientError as error:
                lines.append(f"{label}：不可用（{error}）")
                continue
            if not status.get("gui_running"):
                lines.append(f"{label}：未运行")
            elif status.get("busy"):
                lines.append(f"{label}：运行中，任务 {status.get('task_id') or '未知'}")
            elif target_name == "main_analyzer" and not status.get("config_locked"):
                lines.append(f"{label}：未锁定配置")
            elif target_name == "douyin_downloader" and not status.get("ready"):
                lines.append(f"{label}：未准备好")
            else:
                lines.append(f"{label}：就绪")
        return "\n".join(lines)

    @staticmethod
    def _refusal_reason(target: ActionSpec, status: Mapping[str, object]) -> str | None:
        if not status.get("gui_running"):
            return "主程序未运行" if target.target == "main_analyzer" else "抖音下载程序未运行"
        if status.get("busy"):
            return "主程序当前已有任务运行中" if target.target == "main_analyzer" else "抖音下载程序当前已有任务运行中"
        if target.target == "main_analyzer" and not status.get("config_locked"):
            return "当前配置未锁定，请先在主程序中锁定配置"
        if target.target == "douyin_downloader" and not status.get("ready"):
            return "抖音下载程序当前未准备好"
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
            send_message_to_owner(command_help_text(), config, client)
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
        elif command in {"douyin_fetch_start", "douyin_download_start"}:
            if controller_service is None:
                send_message_to_owner("控制服务尚未初始化，无法执行任务。", config, client)
                return
            action_text = (
                "抖音：开始运行" if command == "douyin_fetch_start" else "抖音：开始下载"
            )
            target = controller_service.registry.resolve(action_text)
            request_id = str(
                getattr(data, "event_id", None)
                or getattr(getattr(data, "event", None), "event_id", None)
                or uuid.uuid4().hex
            )
            response = controller_service.handle_action(target, request_id)
            if getattr(response, "accepted", False):
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
            send_message_to_owner(f"收到指令：{text}", config, client)
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
