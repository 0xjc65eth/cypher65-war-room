"""
HERMES Tool Registry
====================
Central registry of all tools Hermes can use.
"""

from typing import Dict, Any, Callable, List


class ToolRegistry:
    """Registry of callable tools for Hermes."""

    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, func: Callable, description: str = "", category: str = "general"):
        self.tools[name] = {
            "function": func,
            "description": description,
            "category": category,
        }

    def get(self, name: str):
        return self.tools.get(name)

    def list_tools(self) -> List[str]:
        return list(self.tools.keys())

    def list_by_category(self, category: str) -> List[str]:
        return [name for name, t in self.tools.items() if t["category"] == category]