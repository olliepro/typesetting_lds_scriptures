"""Typing base for chapter line builder mixins."""

from __future__ import annotations

from typing import Any


class _LineBuilderBase:
    """Base class to satisfy mixin attribute access during type checking."""

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)
