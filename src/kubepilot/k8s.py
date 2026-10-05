"""Thin wrapper around the official Kubernetes Python client.

API objects are created lazily on first use, so importing this module —
and therefore ``--help`` output, the test suite, and MCP tool discovery —
never requires a live cluster or a kubeconfig file.
"""

from __future__ import annotations

from functools import lru_cache

from kubernetes import client, config as kube_config

from kubepilot.config import settings


def load_kube_configuration() -> None:
    """Load cluster credentials from the environment or kubeconfig file."""
    if settings.in_cluster:
        # Running inside a pod: use the service-account token.
        kube_config.load_incluster_config()
    else:
        kube_config.load_kube_config(config_file=settings.kubeconfig)


@lru_cache(maxsize=1)
def core_v1() -> client.CoreV1Api:
    """Cached CoreV1Api (pods, services, events, logs, …)."""
    load_kube_configuration()
    return client.CoreV1Api()


@lru_cache(maxsize=1)
def apps_v1() -> client.AppsV1Api:
    """Cached AppsV1Api (deployments, …)."""
    load_kube_configuration()
    return client.AppsV1Api()
