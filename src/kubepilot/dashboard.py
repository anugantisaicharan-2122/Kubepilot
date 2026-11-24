"""KubePilot Pro dashboard — web UI over the MCP server's data.

A small ``http.server``-based dashboard (standard library only for the
HTTP layer) that serves a single-page app plus a JSON API. Two modes:

* **LIVE** — data comes from the cluster through the existing MCP tool
  functions in :mod:`kubepilot.server` (so namespace allow-lists,
  read-only refusals and error envelopes behave exactly like the agent
  tools) plus a few direct read-only calls through :mod:`kubepilot.k8s`
  for namespaces, resource requests and rollout history.
* **DEMO** — no cluster is reachable, so a deterministic in-memory
  simulation (:class:`kubepilot.demo_data.DemoStore`, ~100 pods across
  4 namespaces) answers every endpoint, and bulk actions mutate the
  simulation so the UI behaves end-to-end.

Nothing here changes the MCP server: ``server.py``, ``config.py`` and
``k8s.py`` are untouched. Cluster calls run in a thread pool with a
timeout so a hung API server can never hang the dashboard.
"""

from __future__ import annotations

import argparse
import csv
import errno
import io
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from kubepilot import k8s
from kubepilot import server as mcp_server
from kubepilot import __version__
from kubepilot.config import settings
from kubepilot.dashboard_ui import HTML_PAGE
from kubepilot.demo_data import DemoStore, _parse_cpu, _parse_memory

log = logging.getLogger("kubepilot.dashboard")

_TOOL_TIMEOUT = 10  # seconds per cluster call before the API reports a timeout
_MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 20
_EXPORT_LIMIT = 5000


class DashboardError(Exception):
    """A request-level failure, rendered as an ``{"ok": false}`` envelope."""


def _detect_demo() -> bool:
    """True when no cluster is reachable (or demo mode is forced by env)."""
    forced = os.environ.get("KUBEPILOT_DASHBOARD_DEMO", "").strip().lower()
    if forced in {"1", "true", "yes", "y", "on"}:
        return True
    if forced in {"0", "false", "no", "n", "off"}:
        return False
    try:
        k8s.core_v1()
    except Exception:
        return True
    return False


def _paginate(items: list, page: int, page_size: int) -> dict:
    """Slice a list into a paginated API response (server-side paging)."""
    page = max(1, page)
    page_size = min(max(1, page_size), _MAX_PAGE_SIZE)
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    start = (page - 1) * page_size
    return {
        "ok": True,
        "items": items[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": pages,
    }


def _parse_pagination(query: dict) -> tuple[int, int]:
    """Read ?page=&page_size=, tolerating garbage input."""
    try:
        page = int(query.get("page", ["1"])[0])
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(query.get("page_size", [str(_DEFAULT_PAGE_SIZE)])[0])
    except (TypeError, ValueError):
        page_size = _DEFAULT_PAGE_SIZE
    return page, page_size


def _pod_status(pod: dict) -> str:
    """Display status: a Running pod that never gets ready is crash-looping."""
    if pod.get("phase") == "Running" and int(pod.get("restarts") or 0) >= 10:
        return "CrashLoopBackOff"
    return pod.get("phase") or "Unknown"


def _deployment_verdict(dep: dict) -> str:
    r = dep["replicas"]
    if r["ready"] == r["desired"] and r["available"] == r["desired"]:
        return "complete"
    if r["ready"] == 0 and r["desired"] > 0:
        return "stalled"
    return "in_progress"


def _match_label_selector(pod: dict, selector: str) -> bool:
    """True when a pod's labels satisfy an equality-based selector (demo mode).

    Supports the Kubernetes equality-based operators the dashboard's
    filter box accepts: ``k=v`` (equal), ``k!=v`` (not equal — also
    matches when the label is absent, as in Kubernetes) and bare ``k``
    (label exists). Previously only ``k=v`` was handled: ``k!=v`` was
    silently mis-parsed (``partition("=")`` made the key ``"k!"``) so it
    matched nothing, and a bare key always failed.
    """
    labels = pod.get("labels") or {}
    for part in selector.split(","):
        part = part.strip()
        if not part:
            continue
        if "!=" in part:
            key, _, value = part.partition("!=")
            if labels.get(key.strip()) == value.strip():
                return False
        elif "=" in part:
            key, _, value = part.partition("=")
            if labels.get(key.strip()) != value.strip():
                return False
        elif part not in labels:
            return False
    return True


def _to_csv(rows: list[dict], columns: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        flat = {}
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            flat[col] = value
        writer.writerow(flat)
    return buf.getvalue()


class Dashboard:
    """The dashboard application: mode detection, data access, HTTP server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000,
                 demo: bool | None = None) -> None:
        self.host = host
        self.port = port
        self.demo = _detect_demo() if demo is None else bool(demo)
        self.store = DemoStore() if self.demo else None
        self._executor = ThreadPoolExecutor(
            max_workers=16, thread_name_prefix="kubepilot-dash"
        )
        self.httpd: ThreadingHTTPServer | None = None

    # -- low-level call helpers -----------------------------------------
    def _run_tool(self, fn, *args, **kwargs) -> dict:
        """Run an MCP tool function with a timeout; return its envelope."""
        future = self._executor.submit(fn, *args, **kwargs)
        try:
            raw = future.result(timeout=_TOOL_TIMEOUT)
        except FutureTimeoutError:
            raise DashboardError(
                f"cluster request timed out after {_TOOL_TIMEOUT}s"
            )
        except Exception as exc:  # cluster unreachable, bad config, ...
            raise DashboardError(f"cluster request failed: {exc}")
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            raise DashboardError("tool returned non-JSON output")

    def _run_k8s(self, fn):
        """Run a direct kubernetes-client call with a timeout."""
        future = self._executor.submit(fn)
        try:
            return future.result(timeout=_TOOL_TIMEOUT)
        except FutureTimeoutError:
            raise DashboardError(
                f"cluster request timed out after {_TOOL_TIMEOUT}s"
            )
        except Exception as exc:
            raise DashboardError(f"cluster request failed: {exc}")

    def _namespace_allowed_or_error(self, namespace: str) -> dict | None:
        """Error envelope when a namespace is outside the allow-list."""
        if namespace in (None, "all", ""):
            return None
        denied = mcp_server._require_namespace(namespace)
        return json.loads(denied) if denied else None

    def _scope_namespaces(self, namespace: str | None) -> list[str]:
        """Namespaces a request may touch, honouring the allow-list."""
        if namespace not in (None, "all", ""):
            return [namespace]
        if settings.allowed_namespaces:
            return list(settings.allowed_namespaces)
        return self.namespaces()

    # -- normalized data access (live and demo share the shape) ---------
    def namespaces(self) -> list[str]:
        if self.demo:
            return self.store.namespaces()
        if settings.allowed_namespaces:
            return list(settings.allowed_namespaces)
        api = self._run_k8s(lambda: k8s.core_v1().list_namespace())
        return sorted(ns.metadata.name for ns in api.items)

    def _all_pods(self, namespace: str | None = None,
                  label_selector: str = "") -> list[dict]:
        if self.demo:
            pods = self.store.list_pods(namespace)
            if label_selector:
                pods = [p for p in pods if _match_label_selector(p, label_selector)]
            return pods
        ns = namespace if namespace not in (None, "all", "") else settings.default_namespace
        denied = self._namespace_allowed_or_error(ns)
        if denied:
            raise DashboardError(denied["error"])
        envelope = self._run_tool(
            mcp_server.list_pods, namespace=ns, label_selector=label_selector
        )
        if not envelope.get("ok"):
            raise DashboardError(envelope.get("error", "list_pods failed"))
        out = []
        for pod in envelope["pods"]:
            pod = dict(pod)
            pod["namespace"] = ns
            pod["status"] = _pod_status(pod)
            pod.setdefault("labels", {})
            pod.setdefault("cpu_request", None)
            pod.setdefault("memory_request", None)
            pod.setdefault("containers", None)
            out.append(pod)
        return out

    def _all_deployments(self, namespace: str | None = None) -> list[dict]:
        if self.demo:
            return self.store.list_deployments(namespace)
        ns = namespace if namespace not in (None, "all", "") else settings.default_namespace
        denied = self._namespace_allowed_or_error(ns)
        if denied:
            raise DashboardError(denied["error"])
        envelope = self._run_tool(mcp_server.list_deployments, namespace=ns)
        if not envelope.get("ok"):
            raise DashboardError(envelope.get("error", "list_deployments failed"))
        out = []
        for dep in envelope["deployments"]:
            dep = dict(dep)
            dep["namespace"] = ns
            dep["verdict"] = _deployment_verdict(dep)
            dep.setdefault("labels", {})
            out.append(dep)
        return out

    def _all_events(self, namespace: str | None = None,
                    limit: int = 200) -> list[dict]:
        if self.demo:
            return self.store.events_list(namespace, limit=limit)
        ns = namespace if namespace not in (None, "all", "") else settings.default_namespace
        denied = self._namespace_allowed_or_error(ns)
        if denied:
            raise DashboardError(denied["error"])
        envelope = self._run_tool(mcp_server.get_events, namespace=ns, limit=limit)
        if not envelope.get("ok"):
            raise DashboardError(envelope.get("error", "get_events failed"))
        out = []
        for event in envelope["events"]:
            event = dict(event)
            event["namespace"] = ns
            out.append(event)
        return out

    def _all_namespaces_pods(self, namespace: str | None,
                             label_selector: str = "") -> list[dict]:
        """Pods across the scope: 'all' fans out per namespace (live)."""
        if self.demo or namespace not in (None, "all", ""):
            return self._all_pods(namespace, label_selector)
        pods: list[dict] = []
        for ns in self._scope_namespaces(None):
            try:
                pods.extend(self._all_pods(ns, label_selector))
            except DashboardError as exc:
                log.warning("skipping namespace %s: %s", ns, exc)
        return pods

    def _all_namespaces_deployments(self, namespace: str | None) -> list[dict]:
        if self.demo or namespace not in (None, "all", ""):
            return self._all_deployments(namespace)
        deps: list[dict] = []
        for ns in self._scope_namespaces(None):
            try:
                deps.extend(self._all_deployments(ns))
            except DashboardError as exc:
                log.warning("skipping namespace %s: %s", ns, exc)
        return deps

    def _all_namespaces_events(self, namespace: str | None,
                               limit: int = 200) -> list[dict]:
        if self.demo or namespace not in (None, "all", ""):
            return self._all_events(namespace, limit=limit)
        events: list[dict] = []
        for ns in self._scope_namespaces(None):
            try:
                events.extend(self._all_events(ns, limit=limit))
            except DashboardError as exc:
                log.warning("skipping namespace %s: %s", ns, exc)
        events.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
        return events[:limit]

    # -- API implementations ---------------------------------------------
    def api_status(self) -> dict:
        return {
            "ok": True,
            "mode": "demo" if self.demo else "live",
            "version": "0.1.0",
            "namespace": settings.default_namespace,
            "read_only": settings.read_only,
            "allowed_namespaces": list(settings.allowed_namespaces),
            "namespaces": self.namespaces(),
        }

    def api_overview(self, namespace: str | None) -> dict:
        pods = self._all_namespaces_pods(namespace)
        deps = self._all_namespaces_deployments(namespace)
        events = self._all_namespaces_events(namespace, limit=200)
        by_status: dict[str, int] = {}
        restarts = 0
        not_ready = 0
        failed = 0
        for pod in pods:
            status = pod.get("status") or _pod_status(pod)
            by_status[status] = by_status.get(status, 0) + 1
            restarts += int(pod.get("restarts") or 0)
            ready = str(pod.get("ready") or "0/0").split("/")
            try:
                if len(ready) == 2 and int(ready[0]) < int(ready[1]):
                    not_ready += 1
            except ValueError:
                pass
            if status == "Failed":
                failed += 1
        ready_deps = sum(1 for d in deps if d.get("verdict") == "complete")
        warnings = [e for e in events if e.get("type") == "Warning"]
        attention: list[dict] = []
        for pod in pods:
            if (pod.get("status") or _pod_status(pod)) not in ("Running", "Succeeded"):
                attention.append({
                    "title": f"Pod {pod['namespace']}/{pod['name']} is {pod.get('status') or pod.get('phase')}",
                    "detail": f"ready {pod.get('ready')}, {pod.get('restarts')} restarts",
                    "time": None,
                })
        for event in warnings[:5]:
            attention.append({
                "title": f"{event.get('reason')}: {event.get('object')}",
                "detail": (event.get("message") or "")[:160],
                "time": event.get("last_seen"),
            })
        return {
            "ok": True,
            "namespace": namespace or "all",
            "pods": {
                "total": len(pods),
                "running": by_status.get("Running", 0),
                "not_ready": not_ready,
                "restarts": restarts,
                "failed": failed,
                "by_status": by_status,
            },
            "deployments": {
                "total": len(deps),
                "ready": ready_deps,
                "degraded": len(deps) - ready_deps,
            },
            "warning_events": len(warnings),
            "attention": attention[:8],
        }

    def api_pods(self, query: dict) -> dict:
        namespace = query.get("namespace", [None])[0]
        label_selector = query.get("label_selector", [""])[0]
        status = query.get("status", [""])[0]
        search = query.get("search", [""])[0].lower()
        page, page_size = _parse_pagination(query)
        pods = self._all_namespaces_pods(namespace, label_selector)
        if status:
            pods = [p for p in pods if (p.get("status") or _pod_status(p)) == status]
        if search:
            pods = [p for p in pods if search in p["name"].lower()]
        pods.sort(key=lambda p: (p["namespace"], p["name"]))
        return _paginate(pods, page, page_size)

    def api_deployments(self, query: dict) -> dict:
        namespace = query.get("namespace", [None])[0]
        search = query.get("search", [""])[0].lower()
        page, page_size = _parse_pagination(query)
        deps = self._all_namespaces_deployments(namespace)
        if search:
            deps = [d for d in deps if search in d["name"].lower()]
        deps.sort(key=lambda d: (d["namespace"], d["name"]))
        return _paginate(deps, page, page_size)

    def api_events(self, query: dict) -> dict:
        namespace = query.get("namespace", [None])[0]
        event_type = query.get("type", [""])[0]
        search = query.get("search", [""])[0].lower()
        page, page_size = _parse_pagination(query)
        events = self._all_namespaces_events(namespace, limit=200)
        if event_type:
            events = [e for e in events if e.get("type") == event_type]
        if search:
            events = [e for e in events
                      if search in (e.get("reason") or "").lower()
                      or search in (e.get("message") or "").lower()
                      or search in (e.get("object") or "").lower()]
        return _paginate(events, page, page_size)

    def api_logs(self, query: dict) -> dict:
        pod = query.get("pod", [None])[0]
        namespace = query.get("namespace", [None])[0]
        if not pod or not namespace:
            raise DashboardError("query parameters 'pod' and 'namespace' are required")
        container = query.get("container", [""])[0]
        try:
            tail_lines = int(query.get("tail_lines", ["100"])[0])
        except (TypeError, ValueError):
            raise DashboardError("'tail_lines' must be an integer")
        previous = query.get("previous", ["false"])[0].lower() in {"1", "true", "yes"}
        if self.demo:
            ok, text = self.store.logs(pod, namespace, tail_lines=tail_lines, previous=previous)
            return {"ok": ok, "pod": pod, "namespace": namespace,
                    "container": container or "(default)", "tail_lines": tail_lines,
                    "previous": previous,
                    **({"logs": text} if ok else {"error": text})}
        envelope = self._run_tool(
            mcp_server.get_pod_logs, pod_name=pod, namespace=namespace,
            container=container, tail_lines=tail_lines, previous=previous,
        )
        return envelope

    def api_rollout(self, query: dict) -> dict:
        name = query.get("name", [None])[0]
        namespace = query.get("namespace", [None])[0]
        if not name or not namespace:
            raise DashboardError("query parameters 'name' and 'namespace' are required")
        if self.demo:
            ok, data = self.store.rollout(name, namespace)
            return {"ok": ok, **data}
        return self._run_tool(mcp_server.rollout_status, name=name, namespace=namespace)

    def api_rollout_history(self, query: dict) -> dict:
        name = query.get("name", [None])[0]
        namespace = query.get("namespace", [None])[0]
        if not name or not namespace:
            raise DashboardError("query parameters 'name' and 'namespace' are required")
        if self.demo:
            ok, history = self.store.rollout_history(name, namespace)
            if not ok:
                return {"ok": False, "error": f'deployment "{name}" not found in namespace "{namespace}"'}
            return {"ok": True, "deployment": name, "namespace": namespace, "history": history}
        denied = self._namespace_allowed_or_error(namespace)
        if denied:
            return denied
        dep = self._run_k8s(
            lambda: k8s.apps_v1().read_namespaced_deployment(name, namespace)
        )
        current_rev = int(
            (dep.metadata.annotations or {}).get("deployment.kubernetes.io/revision", "0") or 0
        )
        rss = self._run_k8s(
            lambda: k8s.apps_v1().list_namespaced_replica_set(namespace=namespace)
        )
        history = []
        for rs in rss.items:
            owned = any(
                ref.uid == dep.metadata.uid and getattr(ref, "controller", False)
                for ref in (rs.metadata.owner_references or [])
            )
            if not owned:
                continue
            annotations = rs.metadata.annotations or {}
            try:
                rev = int(annotations.get("deployment.kubernetes.io/revision", "0") or 0)
            except ValueError:
                continue
            images = sorted({c.image for c in rs.spec.template.spec.containers})
            created = rs.metadata.creation_timestamp
            history.append({
                "revision": rev,
                "image": images[0] if images else "",
                "created": created.isoformat() if created else "",
                "replicas": rs.spec.replicas or 0,
                "change": "current rollout" if rev == current_rev else "previous revision",
            })
        history.sort(key=lambda h: h["revision"], reverse=True)
        return {"ok": True, "deployment": name, "namespace": namespace, "history": history}

    def api_resources(self, namespace: str | None) -> dict:
        if self.demo:
            return {"ok": True, **self.store.resource_usage(namespace)}
        namespaces = self._scope_namespaces(namespace)
        pods = []
        for ns in namespaces:
            denied = self._namespace_allowed_or_error(ns)
            if denied:
                continue
            api = self._run_k8s(
                lambda ns=ns: k8s.core_v1().list_namespaced_pod(namespace=ns)
            )
            for pod in api.items:
                cpu = 0
                mem = 0
                for container in pod.spec.containers or []:
                    requests = (container.resources.requests or {}) if container.resources else {}
                    if "cpu" in requests:
                        cpu += _parse_cpu(str(requests["cpu"]))
                    if "memory" in requests:
                        mem += _parse_memory(str(requests["memory"]))
                pods.append({
                    "namespace": ns,
                    "app": (pod.metadata.labels or {}).get("app", pod.metadata.name),
                    "cpu_m": cpu, "memory_mib": mem,
                })
        total_cpu = sum(p["cpu_m"] for p in pods)
        total_mem = sum(p["memory_mib"] for p in pods)
        by_ns: dict[str, dict] = {}
        by_dep: dict[str, dict] = {}
        for p in pods:
            slot = by_ns.setdefault(p["namespace"], {"cpu_m": 0, "memory_mib": 0, "pods": 0})
            slot["cpu_m"] += p["cpu_m"]
            slot["memory_mib"] += p["memory_mib"]
            slot["pods"] += 1
            key = f"{p['namespace']}/{p['app']}"
            slot = by_dep.setdefault(key, {"cpu_m": 0, "memory_mib": 0, "pods": 0})
            slot["cpu_m"] += p["cpu_m"]
            slot["memory_mib"] += p["memory_mib"]
            slot["pods"] += 1
        top = sorted(by_dep.items(), key=lambda kv: kv[1]["cpu_m"], reverse=True)[:8]
        return {
            "ok": True,
            "namespace": namespace or "all",
            "pods": len(pods),
            "cpu_millicores": total_cpu,
            "cpu_cores": round(total_cpu / 1000, 2),
            "memory_mib": total_mem,
            "memory_gib": round(total_mem / 1024, 2),
            "by_namespace": by_ns,
            "top_workloads": [{"workload": k, **v} for k, v in top],
        }

    def api_search(self, query: dict) -> dict:
        text = query.get("q", [""])[0].strip()
        if not text:
            raise DashboardError("query parameter 'q' is required")
        namespace = query.get("namespace", [None])[0]
        if self.demo:
            return {"ok": True, **self.store.search(text, namespace)}
        q = text.lower()
        pods = [p for p in self._all_namespaces_pods(namespace) if q in p["name"].lower()][:10]
        deps = [d for d in self._all_namespaces_deployments(namespace) if q in d["name"].lower()][:10]
        events = [e for e in self._all_namespaces_events(namespace, limit=200)
                  if q in (e.get("message") or "").lower()
                  or q in (e.get("reason") or "").lower()][:10]
        return {"ok": True, "pods": pods, "deployments": deps, "events": events}

    def api_describe(self, query: dict) -> dict:
        kind = query.get("kind", [None])[0]
        name = query.get("name", [None])[0]
        namespace = query.get("namespace", [None])[0]
        if not kind or not name:
            raise DashboardError("query parameters 'kind' and 'name' are required")
        if self.demo:
            if kind == "pod":
                pods = [p for p in self.store.list_pods(namespace) if p["name"] == name]
                if not pods:
                    return {"ok": False, "error": f'pod "{name}" not found'}
                return {"ok": True, "kind": kind, "name": name, "resource": pods[0]}
            if kind == "deployment":
                deps = [d for d in self.store.list_deployments(namespace) if d["name"] == name]
                if not deps:
                    return {"ok": False, "error": f'deployment "{name}" not found'}
                return {"ok": True, "kind": kind, "name": name, "resource": deps[0]}
            return {"ok": False, "error": f"unsupported kind '{kind}' in demo mode; use pod or deployment"}
        return self._run_tool(
            mcp_server.describe_resource, kind=kind, name=name,
            namespace=namespace or settings.default_namespace,
        )

    def api_export(self, query: dict) -> tuple[bytes, str, str]:
        """Returns (body, content_type, filename)."""
        kind = query.get("kind", [""])[0]
        fmt = query.get("format", ["json"])[0]
        if kind not in {"pods", "deployments", "events"}:
            raise DashboardError("query parameter 'kind' must be pods, deployments or events")
        if fmt not in {"json", "csv"}:
            raise DashboardError("query parameter 'format' must be json or csv")
        namespace = query.get("namespace", [None])[0]
        if kind == "pods":
            items = self._all_namespaces_pods(
                namespace, query.get("label_selector", [""])[0]
            )
            search = query.get("search", [""])[0].lower()
            status = query.get("status", [""])[0]
            label_selector = query.get("label_selector", [""])[0]
            if label_selector and self.demo:
                items = [p for p in items if _match_label_selector(p, label_selector)]
            if status:
                items = [p for p in items if (p.get("status") or _pod_status(p)) == status]
            if search:
                items = [p for p in items if search in p["name"].lower()]
            columns = ["namespace", "name", "status", "ready", "restarts", "age",
                       "node", "ip", "cpu_request", "memory_request"]
        elif kind == "deployments":
            items = self._all_namespaces_deployments(namespace)
            search = query.get("search", [""])[0].lower()
            if search:
                items = [d for d in items if search in d["name"].lower()]
            columns = ["namespace", "name", "verdict", "images", "age"]
            items = [{**d, "desired": d["replicas"]["desired"],
                      "ready": d["replicas"]["ready"],
                      "updated": d["replicas"]["updated"],
                      "available": d["replicas"]["available"]} for d in items]
            columns = ["namespace", "name", "desired", "ready", "updated",
                       "available", "verdict", "images", "age"]
        else:
            items = self._all_namespaces_events(namespace, limit=_EXPORT_LIMIT)
            event_type = query.get("type", [""])[0]
            search = query.get("search", [""])[0].lower()
            if event_type:
                items = [e for e in items if e.get("type") == event_type]
            if search:
                items = [e for e in items
                         if search in (e.get("reason") or "").lower()
                         or search in (e.get("message") or "").lower()]
            columns = ["namespace", "type", "reason", "object", "message", "count", "last_seen"]
        items = items[:_EXPORT_LIMIT]
        scope = namespace or "all"
        if fmt == "csv":
            body = _to_csv(items, columns).encode()
            return body, "text/csv", f"kubepilot-{kind}-{scope}.csv"
        body = json.dumps(
            {"ok": True, "kind": kind, "namespace": scope,
             "count": len(items), "items": items}, default=str
        ).encode()
        return body, "application/json", f"kubepilot-{kind}-{scope}.json"

    # -- mutations (single + bulk) ----------------------------------------
    def _mutate_one(self, kind: str, item: dict) -> dict:
        """Run one mutation; returns a per-item result dict."""
        name = item.get("name")
        namespace = item.get("namespace") or settings.default_namespace
        if not name:
            return {"ok": False, "name": name, "namespace": namespace,
                    "error": "missing 'name'"}
        try:
            if self.demo:
                if kind == "scale":
                    replicas = item.get("replicas")
                    if not isinstance(replicas, int) or isinstance(replicas, bool) or replicas < 0:
                        return {"ok": False, "name": name, "namespace": namespace,
                                "error": "'replicas' must be an integer >= 0"}
                    result = self.store.scale(name, namespace, replicas)
                elif kind == "restart":
                    result = self.store.restart(name, namespace)
                elif kind == "rollback":
                    result = self.store.rollback(name, namespace)
                else:
                    return {"ok": False, "name": name, "namespace": namespace,
                            "error": f"unknown bulk action '{kind}'"}
            else:
                if kind == "scale":
                    replicas = item.get("replicas")
                    if not isinstance(replicas, int) or isinstance(replicas, bool) or replicas < 0:
                        return {"ok": False, "name": name, "namespace": namespace,
                                "error": "'replicas' must be an integer >= 0"}
                    result = self._run_tool(
                        mcp_server.scale_deployment, name=name,
                        namespace=namespace, replicas=replicas,
                    )
                elif kind == "restart":
                    result = self._run_tool(
                        mcp_server.restart_deployment, name=name, namespace=namespace
                    )
                elif kind == "rollback":
                    result = self._run_tool(
                        mcp_server.rollback_deployment, name=name, namespace=namespace
                    )
                else:
                    return {"ok": False, "name": name, "namespace": namespace,
                            "error": f"unknown bulk action '{kind}'"}
        except DashboardError as exc:
            return {"ok": False, "name": name, "namespace": namespace, "error": str(exc)}
        if not result.get("ok"):
            return {"ok": False, "name": name, "namespace": namespace,
                    "error": result.get("error", "mutation failed")}
        detail = ""
        if kind == "scale":
            detail = f"{result.get('replicas_before')} -> {result.get('replicas_after')} replicas"
        elif kind == "restart":
            detail = f"restarted at {result.get('restarted_at')}"
        elif kind == "rollback":
            detail = f"revision {result.get('revision_before')} -> {result.get('revision_after')}"
        # Keep the full tool envelope (replicas_before/after, restarted_at,
        # revision_before/after, ...) alongside the human-readable detail.
        merged = dict(result)
        merged.update({"name": name, "namespace": namespace, "detail": detail})
        return merged

    def api_bulk(self, kind: str, body: dict) -> dict:
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list) or not items:
            raise DashboardError("request body must be {\"items\": [...]} with at least one deployment")
        if len(items) > 100:
            raise DashboardError("at most 100 deployments per bulk request")
        results = [self._mutate_one(kind, item if isinstance(item, dict) else {})
                   for item in items]
        succeeded = sum(1 for r in results if r["ok"])
        return {
            "ok": True,
            "action": kind,
            "total": len(results),
            "succeeded": succeeded,
            "failed": len(results) - succeeded,
            "results": results,
        }

    def api_single_mutation(self, kind: str, body: dict) -> dict:
        if not isinstance(body, dict):
            raise DashboardError("request body must be a JSON object")
        return self._mutate_one(kind, body)

    # -- HTTP serving -------------------------------------------------------
    def make_handler(self):
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # keep the console clean
                log.debug("%s - %s", self.address_string(), fmt % args)

            def _send(self, status: int, body: bytes, content_type: str,
                      filename: str | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                if filename:
                    self.send_header(
                        "Content-Disposition", f'attachment; filename="{filename}"'
                    )
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _send_json(self, status: int, payload: dict) -> None:
                self._send(status, json.dumps(payload, default=str).encode(),
                           "application/json")

            def _route(self, method: str):
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                query = parse_qs(parsed.query)
                try:
                    if method == "GET" and path == "/":
                        self._send(200, HTML_PAGE.encode(), "text/html; charset=utf-8")
                        return
                    if method != "GET" and path == "/":
                        self._send_json(405, {"ok": False, "error": "method not allowed"})
                        return
                    if not path.startswith("/api/"):
                        self._send_json(404, {"ok": False, "error": f"not found: {path}"})
                        return
                    self._handle_api(method, path, query)
                except DashboardError as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})
                except BrokenPipeError:
                    pass
                except Exception as exc:  # never leak a stack trace to the client
                    log.exception("unhandled error for %s %s", method, path)
                    try:
                        self._send_json(500, {"ok": False, "error": f"internal error: {exc}"})
                    except Exception:
                        pass

            def _read_json_body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if not raw:
                    return {}
                try:
                    body = json.loads(raw)
                except ValueError:
                    raise DashboardError("request body must be valid JSON")
                if not isinstance(body, dict):
                    raise DashboardError("request body must be a JSON object")
                return body

            def _handle_api(self, method: str, path: str, query: dict) -> None:
                get_routes = {
                    "/api/status": lambda: dashboard.api_status(),
                    "/api/namespaces": lambda: {"ok": True, "namespaces": dashboard.namespaces()},
                    "/api/overview": lambda: dashboard.api_overview(query.get("namespace", [None])[0]),
                    "/api/pods": lambda: dashboard.api_pods(query),
                    "/api/deployments": lambda: dashboard.api_deployments(query),
                    "/api/events": lambda: dashboard.api_events(query),
                    "/api/logs": lambda: dashboard.api_logs(query),
                    "/api/rollout": lambda: dashboard.api_rollout(query),
                    "/api/rollout-history": lambda: dashboard.api_rollout_history(query),
                    "/api/resources": lambda: dashboard.api_resources(query.get("namespace", [None])[0]),
                    "/api/search": lambda: dashboard.api_search(query),
                    "/api/describe": lambda: dashboard.api_describe(query),
                }
                if method == "GET" and path == "/api/export":
                    body, content_type, filename = dashboard.api_export(query)
                    self._send(200, body, content_type, filename=filename)
                    return
                if method == "GET" and path in get_routes:
                    self._send_json(200, get_routes[path]())
                    return
                post_routes = {
                    "/api/scale": "scale",
                    "/api/restart": "restart",
                    "/api/rollback": "rollback",
                    "/api/bulk/scale": "bulk-scale",
                    "/api/bulk/restart": "bulk-restart",
                    "/api/bulk/rollback": "bulk-rollback",
                }
                if method == "POST" and path in post_routes:
                    body = self._read_json_body()
                    action = post_routes[path]
                    if action.startswith("bulk-"):
                        payload = dashboard.api_bulk(action[5:], body)
                    else:
                        payload = dashboard.api_single_mutation(action, body)
                    # Single mutations return the tool envelope directly
                    # (ok:false when refused, e.g. read-only mode).
                    self._send_json(200, payload)
                    return
                if path in get_routes or path in post_routes or path == "/api/export":
                    self._send_json(405, {"ok": False, "error": "method not allowed"})
                    return
                self._send_json(404, {"ok": False, "error": f"not found: {path}"})

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def do_PUT(self):
                self._route("PUT")

            def do_DELETE(self):
                self._route("DELETE")

        return Handler

    def serve_forever(self) -> None:
        handler = self.make_handler()
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.httpd.daemon_threads = True
        mode = "DEMO (simulated data)" if self.demo else "LIVE (cluster)"
        log.info("KubePilot Pro dashboard listening on http://%s:%d [%s]",
                 self.host, self.port, mode)
        print(f"KubePilot Pro dashboard: http://{self.host}:{self.port} [{mode}]")
        try:
            self.httpd.serve_forever()
        finally:
            self._executor.shutdown(wait=False)

    def shutdown(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        self._executor.shutdown(wait=False)


def _port_number(value: str) -> int:
    """``argparse`` type for ``--port``: a TCP port number (0-65535).

    Without this, ``--port 99999`` died deep inside ``socket.bind`` with
    an ``OverflowError`` traceback; now argparse rejects it up front
    with a one-line usage error (exit code 2).
    """
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port: {value!r}")
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(
            f"invalid port {port}: must be between 0 and 65535"
        )
    return port


def main(argv: list[str] | None = None) -> None:
    """Run the KubePilot Pro dashboard: ``kubepilot-dashboard``."""
    parser = argparse.ArgumentParser(
        prog="kubepilot-dashboard",
        description="KubePilot Pro — web dashboard for Kubernetes (live or demo mode).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=_port_number, default=8000, help="port (default 8000)")
    parser.add_argument("--demo", action="store_true", help="force demo mode (simulated data)")
    parser.add_argument("--live", action="store_true", help="force live mode (fail if no cluster)")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [kubepilot-dashboard] %(message)s",
    )
    if args.demo and args.live:
        parser.error("--demo and --live are mutually exclusive")
    demo = True if args.demo else False if args.live else None
    dashboard = Dashboard(host=args.host, port=args.port, demo=demo)
    try:
        dashboard.serve_forever()
    except OSError as exc:
        # A failed bind (port in use, bad host, no permission) used to
        # surface as a raw traceback from socketserver; report it as a
        # one-line startup error instead and exit non-zero.
        dashboard._executor.shutdown(wait=False)
        detail = exc.strerror or str(exc)
        hint = (
            " (is another dashboard already running on this port?)"
            if exc.errno == errno.EADDRINUSE
            else ""
        )
        print(
            f"kubepilot-dashboard: error: cannot listen on "
            f"{args.host}:{args.port}: {detail}{hint}",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
