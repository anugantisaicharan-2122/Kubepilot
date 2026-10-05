"""KubePilot — a Model Context Protocol (MCP) server for Kubernetes.

Exposes everyday cluster operations (listing pods, tailing logs, scaling
deployments, reading events, …) as MCP tools so AI agents can inspect and
— when explicitly allowed — operate a Kubernetes cluster safely.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
