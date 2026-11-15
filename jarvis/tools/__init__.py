"""Tools: the controlled capabilities JARVIS can execute."""

from .builtin import register_builtin
from .claude import register_claude
from .mac import register_mac
from .mail_calendar import register_mail_calendar
from .images import register_images
from .registry import Tool, ToolRegistry
from .web import register_web

__all__ = ["Tool", "ToolRegistry", "register_builtin", "register_claude", "register_mac", "register_mail_calendar", "register_images", "register_web"]
