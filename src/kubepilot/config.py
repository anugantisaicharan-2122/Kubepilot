"""Configuration for KubePilot.

Every setting is read from an environment variable so the server can be
configured without code changes — the standard approach for containers
and CI/CD pipelines. See README.md for the full list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _as_bool(value: str | None, default: bool = False) -> bool:
    """Parse a loose boolean environment variable value."""
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def _as_tuple(value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated environment variable into a tuple."""
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _as_int(value: str | None, default: int) -> int:
    """Parse an integer environment variable, falling back on bad input.

    A malformed value (e.g. ``KUBEPILOT_MAX_LOG_LINES=abc``) used to crash
    the whole server at import time. Falling back to the default keeps
    the server bootable with a single misconfigured variable.
    """
    if value is None:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the KubePilot MCP server."""

    kubeconfig: str = field(
        default_factory=lambda: os.environ.get(
            "KUBEPILOT_KUBECONFIG", os.path.expanduser("~/.kube/config")
        )
    )
    in_cluster: bool = field(
        default_factory=lambda: _as_bool(os.environ.get("KUBEPILOT_IN_CLUSTER"))
    )
    allowed_namespaces: tuple[str, ...] = field(
        default_factory=lambda: _as_tuple(
            os.environ.get("KUBEPILOT_ALLOWED_NAMESPACES")
        )
    )
    read_only: bool = field(
        default_factory=lambda: _as_bool(os.environ.get("KUBEPILOT_READ_ONLY"))
    )
    default_namespace: str = field(
        default_factory=lambda: (
            os.environ.get("KUBEPILOT_DEFAULT_NAMESPACE", "").strip() or "default"
        )
    )
    log_level: str = field(
        default_factory=lambda: os.environ.get("KUBEPILOT_LOG_LEVEL", "INFO").upper()
    )
    max_log_lines: int = field(
        default_factory=lambda: _as_int(
            os.environ.get("KUBEPILOT_MAX_LOG_LINES"), 200
        )
    )

    def namespace_allowed(self, namespace: str) -> bool:
        """Return True when a namespace may be accessed.

        An empty allow-list means "no restriction" — set
        KUBEPILOT_ALLOWED_NAMESPACES to scope the server down.
        """
        if not self.allowed_namespaces:
            return True
        return namespace in self.allowed_namespaces


# Import-time singleton: cheap, and keeps tool signatures simple.
settings = Settings()
