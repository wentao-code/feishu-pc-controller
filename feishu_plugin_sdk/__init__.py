"""Shared SDK for local Feishu-controlled plugins."""

from .manifest import PluginManifest
from .remote_control import RemoteControlServer, StatusSnapshot
from .report_client import ReportClient

__all__ = ["PluginManifest", "RemoteControlServer", "ReportClient", "StatusSnapshot"]
