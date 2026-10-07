"""KubePilot MCP server.

Exposes Kubernetes cluster operations as Model Context Protocol tools so
AI agents (Claude, Cursor, …) can inspect — and, when explicitly allowed,
operate — a cluster through a typed, discoverable interface.

Design notes for the curious:
* Every tool returns a JSON string shaped like
  ``{"ok": true, ...}`` or ``{"ok": false, "error": "..."}`` so agents get
  a predictable envelope whatever happens downstream.
* Kubernetes API clients are created lazily (see kubepilot.k8s), so tool
  discovery never needs a live cluster.
* Safety is enforced in code, not just docs: ``KUBEPILOT_READ_ONLY=true``
  makes mutating tools refuse to run, and ``KUBEPILOT_ALLOWED_NAMESPACES``
  scopes every namespaced tool to an allow-list.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from kubernetes import client as k8s_client
from mcp.server.mcpserver import MCPServer

from kubepilot import k8s
from kubepilot.config import settings

log = logging.getLogger("kubepilot")

server = MCPServer(
    name="kubepilot",
    instructions=(
        "KubePilot exposes Kubernetes cluster operations as tools. "
        "Prefer the read-only tools (list_pods, get_pod_logs, "
        "list_deployments, get_events, describe_resource, rollout_status) "
        "when investigating an issue. Only call scale_deployment, "
        "restart_deployment or rollback_deployment when the user explicitly "
        "asked to change a workload, and always report the before/after "
        "state afterwards."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(payload: dict) -> str:
    """Wrap a successful result in the standard JSON envelope."""
    return json.dumps({"ok": True, **payload}, default=str)


def _err(message: str) -> str:
    """Wrap a failure in the standard JSON envelope."""
    return json.dumps({"ok": False, "error": message})


def _require_namespace(namespace: str) -> str | None:
    """Return an error envelope when the namespace is not allow-listed."""
    if not settings.namespace_allowed(namespace):
        allowed = ", ".join(settings.allowed_namespaces)
        return _err(
            f"namespace '{namespace}' is not in KUBEPILOT_ALLOWED_NAMESPACES "
            f"({allowed})"
        )
    return None


def _api_error(exc: Exception) -> str:
    """Turn a Kubernetes (or unexpected) exception into an error envelope."""
    if isinstance(exc, k8s_client.ApiException):
        detail = exc.body.strip() if exc.body else exc.reason
        return _err(f"Kubernetes API error {exc.status}: {detail}")
    return _err(f"{type(exc).__name__}: {exc}")


def _age(created) -> str:
    """Human-friendly age like '2d4h', '36m' or '45s'."""
    if created is None:
        return "unknown"
    delta = datetime.now(timezone.utc) - created.astimezone(timezone.utc)
    seconds = int(delta.total_seconds())
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def _summarize_pod(pod) -> dict:
    statuses = pod.status.container_statuses or []
    ready = sum(1 for c in statuses if c.ready)
    return {
        "name": pod.metadata.name,
        "phase": pod.status.phase,
        "ready": f"{ready}/{len(statuses)}",
        "restarts": sum(c.restart_count for c in statuses),
        "age": _age(pod.metadata.creation_timestamp),
        "ip": pod.status.pod_ip,
        "node": pod.spec.node_name,
    }


def _summarize_deployment(dep) -> dict:
    spec, status = dep.spec, dep.status
    return {
        "name": dep.metadata.name,
        "replicas": {
            "desired": spec.replicas,
            "ready": status.ready_replicas or 0,
            "updated": status.updated_replicas or 0,
            "available": status.available_replicas or 0,
        },
        "images": sorted({c.image for c in spec.template.spec.containers}),
        "age": _age(dep.metadata.creation_timestamp),
    }


def _event_time(event):
    for attr in ("last_timestamp", "event_time"):
        ts = getattr(event, attr, None)
        if ts:
            return ts
    return event.metadata.creation_timestamp


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------

@server.tool()
def list_pods(
    namespace: str = settings.default_namespace, label_selector: str = ""
) -> str:
    """List pods in a namespace, optionally filtered by a label selector.

    Start here when investigating a workload: shows each pod's phase,
    container readiness (ready/total), restart counts and age. Narrow
    results with a Kubernetes label selector, e.g. "app=checkout,env=prod".
    """
    if denied := _require_namespace(namespace):
        return denied
    try:
        pods = (
            k8s.core_v1()
            .list_namespaced_pod(
                namespace=namespace, label_selector=label_selector or None
            )
            .items
        )
        return _ok(
            {
                "namespace": namespace,
                "count": len(pods),
                "pods": [_summarize_pod(p) for p in pods],
            }
        )
    except Exception as exc:  # surfaced to the agent as JSON, never raised
        return _api_error(exc)


@server.tool()
def get_pod_logs(
    pod_name: str,
    namespace: str = settings.default_namespace,
    container: str = "",
    tail_lines: int = 100,
) -> str:
    """Fetch recent log lines for a pod's container.

    The fastest way to see why a pod is crash-looping or failing its
    probes. Omit `container` to use the pod's default container.
    `tail_lines` is capped by KUBEPILOT_MAX_LOG_LINES (default 200) so
    responses stay small enough for an agent to digest.
    """
    if denied := _require_namespace(namespace):
        return denied
    tail_lines = max(1, min(int(tail_lines), settings.max_log_lines))
    try:
        logs = k8s.core_v1().read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container or None,
            tail_lines=tail_lines,
        )
        return _ok(
            {
                "pod": pod_name,
                "namespace": namespace,
                "container": container or "(default)",
                "tail_lines": tail_lines,
                "logs": logs or "",
            }
        )
    except Exception as exc:
        return _api_error(exc)


@server.tool()
def list_deployments(namespace: str = settings.default_namespace) -> str:
    """List deployments in a namespace with replica and image status.

    Shows desired vs ready/updated/available replicas per deployment —
    the quickest way to spot a rollout that is stuck or degraded — plus
    the container images each deployment is running.
    """
    if denied := _require_namespace(namespace):
        return denied
    try:
        deps = (
            k8s.apps_v1().list_namespaced_deployment(namespace=namespace).items
        )
        return _ok(
            {
                "namespace": namespace,
                "count": len(deps),
                "deployments": [_summarize_deployment(d) for d in deps],
            }
        )
    except Exception as exc:
        return _api_error(exc)


@server.tool()
def get_events(namespace: str = settings.default_namespace, limit: int = 50) -> str:
    """List recent Kubernetes events in a namespace, newest first.

    Events are the cluster's diary: failed scheduling, image-pull errors,
    probe failures and OOM kills all land here. Reach for this when a
    workload is misbehaving but pod logs are empty or the pod never
    started.
    """
    if denied := _require_namespace(namespace):
        return denied
    limit = max(1, min(int(limit), 200))
    try:
        events = k8s.core_v1().list_namespaced_event(namespace=namespace).items
        events.sort(key=_event_time, reverse=True)
        return _ok(
            {
                "namespace": namespace,
                "count": min(len(events), limit),
                "events": [
                    {
                        "type": e.type,
                        "reason": e.reason,
                        "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                        "message": (e.message or "")[:300],
                        "count": e.count,
                        "last_seen": _event_time(e).isoformat(),
                    }
                    for e in events[:limit]
                ],
            }
        )
    except Exception as exc:
        return _api_error(exc)


@server.tool()
def describe_resource(
    kind: str, name: str, namespace: str = settings.default_namespace
) -> str:
    """Return the full manifest of a Kubernetes resource as JSON.

    `kind` is one of: pod, deployment, service, configmap, namespace, node.
    For cluster-scoped kinds (namespace, node) the namespace argument is
    ignored. `metadata.managedFields` is stripped to keep the output
    compact for agent consumption.
    """
    kind = kind.strip().lower()
    readers = {
        "pod": lambda: k8s.core_v1().read_namespaced_pod(name, namespace),
        "service": lambda: k8s.core_v1().read_namespaced_service(name, namespace),
        "configmap": lambda: k8s.core_v1().read_namespaced_config_map(
            name, namespace
        ),
        "deployment": lambda: k8s.apps_v1().read_namespaced_deployment(
            name, namespace
        ),
        "namespace": lambda: k8s.core_v1().read_namespace(name),
        "node": lambda: k8s.core_v1().read_node(name),
    }
    if kind not in readers:
        return _err(
            f"unsupported kind '{kind}'; expected one of: "
            + ", ".join(sorted(readers))
        )
    if kind not in {"namespace", "node"}:
        if denied := _require_namespace(namespace):
            return denied
    try:
        data = readers[kind]().to_dict()
        # managedFields is server-side noise; agents don't need it.
        metadata = data.get("metadata") or {}
        metadata.pop("managed_fields", None)
        return _ok({"kind": kind, "name": name, "resource": data})
    except Exception as exc:
        return _api_error(exc)


# ---------------------------------------------------------------------------
# Rollout controls
# ---------------------------------------------------------------------------

def _deployment_revision(dep) -> int:
    """Current revision of a deployment from its revision annotation."""
    annotations = (dep.metadata.annotations or {})
    try:
        return int(annotations.get("deployment.kubernetes.io/revision", "0"))
    except (TypeError, ValueError):
        return 0


def _previous_revision(dep, replica_sets):
    """Find the newest ReplicaSet older than the deployment's revision.

    Returns ``(revision, pod_template)`` where the template is a plain
    dict ready to patch into the deployment, or ``None`` when there is
    no earlier revision to roll back to.
    """
    current = _deployment_revision(dep)
    best = None
    for rs in replica_sets:
        owned = any(
            ref.uid == dep.metadata.uid and getattr(ref, "controller", False)
            for ref in (rs.metadata.owner_references or [])
        )
        if not owned:
            continue
        rev = _deployment_revision(rs)
        if rev < current and (best is None or rev > best[0]):
            best = (rev, rs.spec.template)
    if best is None:
        return None
    rev, template = best
    if hasattr(template, "to_dict"):
        template = template.to_dict()
    return rev, template


@server.tool()
def rollout_status(
    name: str, namespace: str = settings.default_namespace
) -> str:
    """Report a deployment's rollout progress (read-only).

    Compares desired vs updated/ready/available replicas and surfaces the
    deployment's conditions, with a simple verdict: "complete" when every
    replica is updated, ready and available; "stalled" when the progress
    deadline was exceeded; otherwise "in_progress". Start here before
    deciding whether a restart or rollback is warranted.
    """
    if denied := _require_namespace(namespace):
        return denied
    try:
        dep = k8s.apps_v1().read_namespaced_deployment(name, namespace)
        spec, status = dep.spec, dep.status
        desired = spec.replicas or 0
        updated = status.updated_replicas or 0
        ready = status.ready_replicas or 0
        available = status.available_replicas or 0
        conditions = [
            {
                "type": c.type,
                "status": c.status,
                "reason": c.reason,
                "message": (c.message or "")[:300],
            }
            for c in (status.conditions or [])
        ]
        stalled = any(
            c.get("type") == "Progressing"
            and c.get("reason") == "ProgressDeadlineExceeded"
            and c.get("status") == "True"
            for c in conditions
        )
        if stalled:
            verdict = "stalled"
        elif updated == desired and ready == desired and available == desired:
            verdict = "complete"
        else:
            verdict = "in_progress"
        return _ok(
            {
                "deployment": name,
                "namespace": namespace,
                "revision": _deployment_revision(dep),
                "replicas": {
                    "desired": desired,
                    "updated": updated,
                    "ready": ready,
                    "available": available,
                    "unavailable": status.unavailable_replicas or 0,
                },
                "conditions": conditions,
                "verdict": verdict,
            }
        )
    except Exception as exc:
        return _api_error(exc)


@server.tool()
def restart_deployment(
    name: str, namespace: str = settings.default_namespace
) -> str:
    """Restart a deployment's rollout (MUTATING).

    The equivalent of `kubectl rollout restart`: patches the pod template's
    `kubectl.kubernetes.io/restartedAt` annotation so every pod is
    recreated with the same image and config. Useful when pods are wedged
    but the spec itself is fine. Refused when the server runs with
    KUBEPILOT_READ_ONLY=true.
    """
    if settings.read_only:
        return _err(
            "refusing to restart: server is running in read-only mode "
            "(KUBEPILOT_READ_ONLY=true)"
        )
    if denied := _require_namespace(namespace):
        return denied
    try:
        apps = k8s.apps_v1()
        dep = apps.read_namespaced_deployment(name, namespace)
        restarted_at = datetime.now(timezone.utc).isoformat()
        apps.patch_namespaced_deployment(
            name,
            namespace,
            {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": restarted_at
                            }
                        }
                    }
                }
            },
        )
        log.info(
            "restarted deployment %s/%s (revision %s)",
            namespace,
            name,
            _deployment_revision(dep),
        )
        return _ok(
            {
                "deployment": name,
                "namespace": namespace,
                "restarted_at": restarted_at,
            }
        )
    except Exception as exc:
        return _api_error(exc)


@server.tool()
def rollback_deployment(
    name: str, namespace: str = settings.default_namespace
) -> str:
    """Roll a deployment back to its previous revision (MUTATING).

    Finds the newest ReplicaSet older than the deployment's current
    revision and patches the deployment's pod template back to it — the
    same thing `kubectl rollout undo` does. (The kubernetes Python client
    no longer ships a dedicated rollback endpoint, so KubePilot walks the
    revision history itself.) Fails cleanly when there is no earlier
    revision. Refused when the server runs with KUBEPILOT_READ_ONLY=true.
    """
    if settings.read_only:
        return _err(
            "refusing to roll back: server is running in read-only mode "
            "(KUBEPILOT_READ_ONLY=true)"
        )
    if denied := _require_namespace(namespace):
        return denied
    try:
        apps = k8s.apps_v1()
        dep = apps.read_namespaced_deployment(name, namespace)
        current_rev = _deployment_revision(dep)
        replica_sets = apps.list_namespaced_replica_set(
            namespace=namespace
        ).items
        previous = _previous_revision(dep, replica_sets)
        if previous is None:
            return _err(
                f"no earlier revision found for deployment '{name}' "
                f"(current revision: {current_rev})"
            )
        target_rev, template = previous
        apps.patch_namespaced_deployment(
            name, namespace, {"spec": {"template": template}}
        )
        log.info(
            "rolled back deployment %s/%s: revision %s -> %s",
            namespace,
            name,
            current_rev,
            target_rev,
        )
        return _ok(
            {
                "deployment": name,
                "namespace": namespace,
                "revision_before": current_rev,
                "revision_after": target_rev,
            }
        )
    except Exception as exc:
        return _api_error(exc)


# ---------------------------------------------------------------------------
# Mutating tools
# ---------------------------------------------------------------------------

@server.tool()
def scale_deployment(
    name: str,
    namespace: str = settings.default_namespace,
    replicas: int = 1,
) -> str:
    """Change a deployment's replica count (MUTATING).

    Only call this when the user explicitly asked to scale a workload up
    or down. The call is refused when the server runs with
    KUBEPILOT_READ_ONLY=true. Returns replica counts before and after so
    the change can be confirmed.
    """
    if settings.read_only:
        return _err(
            "refusing to scale: server is running in read-only mode "
            "(KUBEPILOT_READ_ONLY=true)"
        )
    if denied := _require_namespace(namespace):
        return denied
    if replicas < 0:
        return _err("replicas must be 0 or greater")
    try:
        apps = k8s.apps_v1()
        before = apps.read_namespaced_deployment_scale(name, namespace).spec.replicas
        apps.patch_namespaced_deployment_scale(
            name, namespace, {"spec": {"replicas": int(replicas)}}
        )
        log.info(
            "scaled deployment %s/%s: %s -> %s replicas",
            namespace,
            name,
            before,
            replicas,
        )
        return _ok(
            {
                "deployment": name,
                "namespace": namespace,
                "replicas_before": before,
                "replicas_after": int(replicas),
            }
        )
    except Exception as exc:
        return _api_error(exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the KubePilot MCP server over stdio."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [kubepilot] %(message)s",
    )
    if settings.read_only:
        log.warning("read-only mode: mutating tools will refuse to run")
    if settings.allowed_namespaces:
        log.info(
            "namespace allow-list: %s", ", ".join(settings.allowed_namespaces)
        )
    else:
        log.warning("no namespace allow-list set: all namespaces are accessible")
    log.info("starting KubePilot MCP server (stdio transport)")
    server.run(transport="stdio")
