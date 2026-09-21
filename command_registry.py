"""Map human Feishu commands to stable gateway actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpec:
    action: str
    target: str
    target_action: str
    label: str


_COMMANDS = {
    "抖音开始运行": ActionSpec(
        "douyin.fetch.start", "main_analyzer", "start", "抖音抓取"
    ),
    "抖音开始下载": ActionSpec(
        "douyin.download.start", "douyin_downloader", "start", "抖音视频下载"
    ),
    "状态": ActionSpec("system.status", "all", "status", "系统状态"),
}


def normalize_command(text: str) -> str | None:
    normalized = "".join(str(text or "").strip().lower().split())
    normalized = normalized.replace("：", "").replace(":", "")
    if normalized in {"抖音开始运行", "douyinstart", "douyinrun"}:
        return "douyin.fetch.start"
    if normalized in {"抖音开始下载", "抖音视频下载", "douyindownload"}:
        return "douyin.download.start"
    if normalized in {"状态", "status", "systemstatus"}:
        return "system.status"
    return None


class CommandRegistry:
    def resolve(self, command: str) -> ActionSpec | None:
        action = normalize_command(command)
        if action is None:
            return None
        for spec in _COMMANDS.values():
            if spec.action == action:
                return spec
        return None

    @staticmethod
    def help_text() -> str:
        return (
            "可用指令：\n"
            "1. 抖音：开始运行：按主程序锁定配置开始抓取\n"
            "2. 抖音：开始下载：按下载器当前设置开始下载\n"
            "3. 状态：查看两个程序的运行状态\n"
            "4. 帮助：显示本指令列表"
        )
