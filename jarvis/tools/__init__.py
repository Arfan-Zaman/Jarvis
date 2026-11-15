"""Tools: the controlled capabilities JARVIS can execute."""

from .builtin import register_builtin
from .claude import register_claude
from .registry import Tool, ToolRegistry
from .web import register_web

__all__ = ["Tool", "ToolRegistry", "register_builtin", "register_claude", "register_web"]
