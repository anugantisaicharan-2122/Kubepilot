"""Deterministic demo data for the KubePilot dashboard.

When no cluster is reachable the dashboard runs in DEMO MODE against
:class:`DemoStore` — a realistic, seeded simulation of a multi-namespace
cluster (~100 pods, ~15 deployments, ~60 events) with mutable state, so
bulk actions (scale / restart / rollback) behave end-to-end without a
cluster. Nothing here touches a real cluster or the MCP server.
"""

from __future__ import annotations

import random
import string
from copy import deepcopy
from datetime import datetime, timedelta, timezone

_SEED = 20261120

# (name, namespace, replicas, images, labels)
_DEPLOYMENTS = [
    ("checkout-api", "prod", 3, ["registry/checkout-api:2.4.1"]),
    ("payments-worker", "prod", 3, ["registry/payments-worker:1.9.0"]),
    ("web-frontend", "prod", 2, ["registry/web-frontend:2.4.1"]),
    ("inventory-sync", "prod", 1, ["registry/inventory-sync:0.8.2"]),
    ("search-api", "prod", 2, ["registry/search-api:3.1.0"]),
    ("notifications", "prod", 2, ["registry/notify:1.2.0"]),
    ("checkout-api", "staging", 2, ["registry/checkout-api:2.4.1"]),
    ("web-frontend", "staging", 2, ["registry/web-frontend:2.4.1"]),
    ("api-gateway", "staging", 1, ["registry/api-gateway:0.9.4"]),
    ("demo-app", "default", 1, ["registry/demo-app:0.1.0"]),
    ("redis-cache", "default", 1, ["redis:7.2"]),
    ("worker", "default", 2, ["registry/worker:0.5.3"]),
    ("prometheus", "monitoring", 1, ["prom/prometheus:v2.53.0"]),
    ("grafana", "monitoring", 1, ["grafana/grafana:11.2.0"]),
    ("alertmanager", "monitoring", 1, ["prom/alertmanager:v0.27.0"]),
]

# Extra standalone pods per namespace, on top of deployment pods.
_EXTRA_PODS = {"prod": 38, "staging": 14, "default": 11, "monitoring": 5}
_EXTRA_APPS = [
    "api", "worker", "cache", "cron-backup", "batch-report", "ingest",
    "scheduler", "gateway", "auth", "billing", "metrics", "queue",
]

_CPU_CHOICES = ["100m", "250m", "500m", "1"]
_MEM_CHOICES = ["128Mi", "256Mi", "512Mi", "1Gi"]
_NODES = ["node-1", "node-2", "node-3"]


def _age_str(created: datetime) -> str:
    """Human-friendly age like '2d4h', '36m' or '45s' (same shape as the MCP tools)."""
    delta = datetime.now(timezone.utc) - created
    seconds = max(0, int(delta.total_seconds()))
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


def _parse_cpu(value: str) -> int:
    """CPU request string -> millicores (e.g. '250m' -> 250, '1' -> 1000)."""
    value = value.strip()
    if value.endswith("m"):
        return int(value[:-1])
    return int(float(value) * 1000)


def _parse_memory(value: str) -> int:
    """Memory request string -> MiB (e.g. '512Mi' -> 512, '1Gi' -> 1024)."""
    value = value.strip()
    if value.endswith("Gi"):
        return int(float(value[:-2]) * 1024)
    if value.endswith("Mi"):
        return int(float(value[:-2]))
    if value.endswith("Ki"):
        return max(1, int(float(value[:-2]) / 1024))
    return int(value)  # bare bytes are not expected; treat as MiB floor


class DemoStore:
    """In-memory simulated cluster. Deterministic: same seed, same data."""

    def __init__(self, seed: int = _SEED) -> None:
        self._rng = random.Random(seed)
        self._now = datetime.now(timezone.utc)
        self.pods: list[dict] = []
        self.deployments: list[dict] = []
        self.events: list[dict] = []
        self._history: dict[tuple[str, str], list[dict]] = {}
        self._restarted_at: dict[tuple[str, str], str] = {}
        self._build()

    # -- construction ----------------------------------------------------
    def _suffix(self, n: int = 5) -> str:
        alphabet = string.ascii_lowercase + string.digits
        return "".join(self._rng.choice(alphabet) for _ in range(n))

    def _created(self, max_age_days: float = 12.0) -> datetime:
        minutes = self._rng.randint(5, int(max_age_days * 24 * 60))
        return self._now - timedelta(minutes=minutes)

    def _pod(
        self, name: str, namespace: str, app: str, *, phase: str = "Running",
        ready: str = "1/1", restarts: int = 0,
        created: datetime | None = None,
    ) -> dict:
        created = created or self._created()
        return {
            "name": name,
            "namespace": namespace,
            "phase": phase,
            "ready": ready,
            "restarts": restarts,
            "age": _age_str(created),
            "created": created,
            "ip": f"10.0.{self._rng.randint(1, 3)}.{self._rng.randint(2, 250)}",
            "node": self._rng.choice(_NODES),
            "labels": {"app": app, "env": namespace},
            "cpu_request": self._rng.choice(_CPU_CHOICES),
            "memory_request": self._rng.choice(_MEM_CHOICES),
            "containers": 1,
        }

    def _build(self) -> None:
        for name, namespace, replicas, images in _DEPLOYMENTS:
            created = self._created(max_age_days=30)
            dep = {
                "name": name,
                "namespace": namespace,
                "replicas": {
                    "desired": replicas,
                    "ready": replicas,
                    "updated": replicas,
                    "available": replicas,
                },
                "images": sorted(set(images)),
                "age": _age_str(created),
                "created": created,
                "revision": self._rng.choice([2, 3, 3, 4]),
                "labels": {"app": name, "env": namespace},
            }
            self.deployments.append(dep)
            for i in range(replicas):
                pod = self._pod(
                    f"{name}-{self._suffix()}-{self._suffix()}",
                    namespace, name,
                    ready="1/1",
                    restarts=self._rng.choice([0, 0, 0, 1, 2]),
                    created=self._now - timedelta(
                        minutes=self._rng.randint(20, 60 * 24 * 3)
                    ),
                )
                pod["containers"] = 2 if name in {"checkout-api", "payments-worker"} else 1
                pod["ready"] = "2/2" if pod["containers"] == 2 else "1/1"
                self.pods.append(pod)
            self._history[(namespace, name)] = self._revision_history(dep)

        # Degraded cases, mirroring the tutorial's incident story.
        self._degrade_payments()
        self._degrade_inventory()
        self._add_failed_batch()
        self._add_extra_pods()
        self._build_events()

    def _revision_history(self, dep: dict) -> list[dict]:
        """Newest-first revision list for a deployment."""
        current = dep["revision"]
        images = dep["images"]
        base = images[0]
        history = []
        for rev in range(current, max(0, current - 3), -1):
            if rev == current:
                image = base
            else:
                # Older revisions ran the previous patch/minor.
                image = base.rsplit(":", 1)[0] + f":prev-{rev}"
            history.append({
                "revision": rev,
                "image": image,
                "created": (
                    dep["created"] - timedelta(days=(current - rev) * 3)
                ).isoformat(),
                "replicas": dep["replicas"]["desired"],
                "change": (
                    "current rollout" if rev == current
                    else f"rolled back from revision {rev + 1}"
                ),
            })
        return history

    def _degrade_payments(self) -> None:
        """One payments-worker pod crash-loops (OOMKilled, 14 restarts)."""
        pods = [p for p in self.pods if p["name"].startswith("payments-worker-")]
        if not pods:
            return
        victim = pods[0]
        victim.update({
            "phase": "Running", "ready": "0/2", "restarts": 14,
            "cpu_request": "250m", "memory_request": "256Mi",
        })
        dep = next(
            d for d in self.deployments
            if d["name"] == "payments-worker" and d["namespace"] == "prod"
        )
        dep["replicas"]["ready"] = 2
        dep["replicas"]["available"] = 2

    def _degrade_inventory(self) -> None:
        """inventory-sync stays Pending (unschedulable)."""
        pods = [p for p in self.pods if p["name"].startswith("inventory-sync-")]
        if not pods:
            return
        pods[0].update({"phase": "Pending", "ready": "0/1", "restarts": 0, "ip": None})
        dep = next(
            d for d in self.deployments
            if d["name"] == "inventory-sync" and d["namespace"] == "prod"
        )
        dep["replicas"].update({"ready": 0, "updated": 0, "available": 0})

    def _add_failed_batch(self) -> None:
        self.pods.append(self._pod(
            f"batch-report-{self._suffix()}", "default", "batch-report",
            phase="Failed", ready="0/1", restarts=3,
        ))

    def _add_extra_pods(self) -> None:
        for namespace, count in _EXTRA_PODS.items():
            for i in range(count):
                app = self._rng.choice(_EXTRA_APPS)
                phase = self._rng.choices(
                    ["Running", "Running", "Running", "Running", "Pending", "Succeeded"],
                    weights=[82, 6, 4, 3, 3, 2],
                )[0]
                ready = "1/1" if phase == "Running" else "0/1"
                self.pods.append(self._pod(
                    f"{app}-{i}-{self._suffix()}", namespace, app,
                    phase=phase, ready=ready,
                    restarts=self._rng.choice([0, 0, 0, 1, 3]),
                ))

    def _build_events(self) -> None:
        templates = [
            ("Normal", "Scheduled", "Pod/{pod}", "Successfully assigned {ns}/{pod} to {node}"),
            ("Normal", "Pulled", "Pod/{pod}", 'Container image "{img}" already present on machine'),
            ("Normal", "Created", "Pod/{pod}", "Created container {app}"),
            ("Normal", "Started", "Pod/{pod}", "Started container {app}"),
            ("Normal", "ScalingReplicaSet", "Deployment/{dep}", "Scaled up replica set {dep} to {n}"),
            ("Warning", "BackOff", "Pod/{pod}", "Back-off restarting failed container {app} in pod {ns}/{pod}"),
            ("Warning", "FailedScheduling", "Pod/{pod}", "0/3 nodes are available: 3 Insufficient cpu."),
            ("Warning", "OOMKilling", "Pod/{pod}", "Memory cgroup out of memory: Killed process (app) total-vm:524288kB"),
            ("Warning", "Unhealthy", "Pod/{pod}", "Readiness probe failed: HTTP probe failed with statuscode: 503"),
            ("Warning", "FailedMount", "Pod/{pod}", 'Unable to attach or mount volumes: unmounted volumes=[config]'),
        ]
        pods = [p for p in self.pods if p["namespace"] in {"prod", "staging"}]
        for _ in range(60):
            kind, reason, obj_tpl, msg_tpl = self._rng.choice(templates)
            pod = self._rng.choice(pods)
            obj = obj_tpl.format(
                pod=pod["name"],
                dep=pod["labels"]["app"],
            )
            message = msg_tpl.format(
                ns=pod["namespace"], pod=pod["name"], node=pod["node"],
                img="registry/app:latest", app=pod["labels"]["app"], n=3,
                dep=pod["labels"]["app"],
            )
            when = self._now - timedelta(minutes=self._rng.randint(1, 360))
            self.events.append({
                "type": kind,
                "reason": reason,
                "object": obj,
                "message": message,
                "count": self._rng.choice([1, 1, 1, 2, 3, 5]),
                "last_seen": when.isoformat(),
                "namespace": pod["namespace"],
                "_ts": when,
            })
        self.events.sort(key=lambda e: e["_ts"], reverse=True)

    # -- read API ----------------------------------------------------------
    def namespaces(self) -> list[str]:
        return sorted({p["namespace"] for p in self.pods} | {d["namespace"] for d in self.deployments})

    def list_pods(self, namespace: str | None = None) -> list[dict]:
        items = self.pods if namespace in (None, "all") else [
            p for p in self.pods if p["namespace"] == namespace
        ]
        return [self._public_pod(p) for p in items]

    @staticmethod
    def _public_pod(pod: dict) -> dict:
        out = {k: v for k, v in pod.items() if k != "created"}
        out["status"] = DemoStore._status_of(pod)
        return out

    @staticmethod
    def _status_of(pod: dict) -> str:
        """Display status: CrashLoopBackOff when a Running pod never gets ready."""
        if pod["phase"] == "Running" and pod["restarts"] >= 10:
            return "CrashLoopBackOff"
        return pod["phase"]

    def list_deployments(self, namespace: str | None = None) -> list[dict]:
        items = self.deployments if namespace in (None, "all") else [
            d for d in self.deployments if d["namespace"] == namespace
        ]
        return [self._public_deployment(d) for d in items]

    def _public_deployment(self, dep: dict) -> dict:
        out = {k: v for k, v in dep.items() if k != "created"}
        out["verdict"] = self._verdict(dep)
        return out

    @staticmethod
    def _verdict(dep: dict) -> str:
        r = dep["replicas"]
        if r["ready"] == r["desired"] and r["available"] == r["desired"]:
            return "complete"
        if r["ready"] == 0 and r["desired"] > 0:
            return "stalled"
        return "in_progress"

    def events_list(self, namespace: str | None = None, limit: int = 200) -> list[dict]:
        items = self.events if namespace in (None, "all") else [
            e for e in self.events if e["namespace"] == namespace
        ]
        return [
            {k: v for k, v in e.items() if k != "_ts"}
            for e in items[:limit]
        ]

    def logs(self, pod_name: str, namespace: str, *, tail_lines: int = 100,
             previous: bool = False) -> tuple[bool, str]:
        pod = next(
            (p for p in self.pods
             if p["name"] == pod_name and p["namespace"] == namespace),
            None,
        )
        if pod is None:
            return False, f'pod "{pod_name}" not found in namespace "{namespace}"'
        if pod["phase"] == "Pending":
            return True, "(no logs yet — pod has not started)"
        app = pod["labels"]["app"]
        lines: list[str] = []
        base = self._now - timedelta(minutes=tail_lines)
        if previous and pod["restarts"] >= 10:
            lines = [
                f"{(base + timedelta(seconds=30 * i)).isoformat()}Z FATAL {app}: "
                "out of memory (OOMKilled) — container exceeded 256Mi limit"
                for i in range(min(tail_lines, 12))
            ]
            lines.append(
                f"{self._now.isoformat()}Z INFO  {app}: previous instance "
                "terminated, exit code 137"
            )
            return True, "\n".join(lines)
        for i in range(tail_lines):
            ts = (base + timedelta(seconds=7 * i)).isoformat()
            msg = self._rng.choice([
                f"INFO  {app}: request completed method=GET path=/api/health status=200 duration=3ms",
                f"INFO  {app}: worker heartbeat ok queue_depth={self._rng.randint(0, 12)}",
                f"INFO  {app}: cache hit ratio={self._rng.randint(80, 99)}% window=60s",
                f"DEBUG {app}: gc pause {self._rng.randint(2, 18)}ms heap={self._rng.randint(90, 220)}Mi",
                f"INFO  {app}: connection pool open={self._rng.randint(2, 9)} idle={self._rng.randint(0, 4)}",
            ])
            lines.append(f"{ts}Z {msg}")
        return True, "\n".join(lines)

    def rollout(self, name: str, namespace: str) -> tuple[bool, dict]:
        dep = next(
            (d for d in self.deployments
             if d["name"] == name and d["namespace"] == namespace),
            None,
        )
        if dep is None:
            return False, {"error": f'deployment "{name}" not found in namespace "{namespace}"'}
        r = dep["replicas"]
        return True, {
            "deployment": name,
            "namespace": namespace,
            "revision": dep["revision"],
            "replicas": dict(r, unavailable=r["desired"] - r["available"]),
            "conditions": [{
                "type": "Available", "status": "True" if r["available"] == r["desired"] else "False",
                "reason": "MinimumReplicasAvailable",
                "message": f"Deployment has minimum availability ({r['available']}/{r['desired']}).",
            }],
            "verdict": self._verdict(dep),
        }

    def rollout_history(self, name: str, namespace: str) -> tuple[bool, list[dict]]:
        history = self._history.get((namespace, name))
        if history is None:
            return False, []
        return True, deepcopy(history)

    def resource_usage(self, namespace: str | None = None) -> dict:
        pods = self.pods if namespace in (None, "all") else [
            p for p in self.pods if p["namespace"] == namespace
        ]
        total_cpu = sum(_parse_cpu(p["cpu_request"]) for p in pods)
        total_mem = sum(_parse_memory(p["memory_request"]) for p in pods)
        by_ns: dict[str, dict] = {}
        for p in pods:
            slot = by_ns.setdefault(p["namespace"], {"cpu_m": 0, "memory_mib": 0, "pods": 0})
            slot["cpu_m"] += _parse_cpu(p["cpu_request"])
            slot["memory_mib"] += _parse_memory(p["memory_request"])
            slot["pods"] += 1
        by_dep: dict[str, dict] = {}
        for p in pods:
            key = f'{p["namespace"]}/{p["labels"]["app"]}'
            slot = by_dep.setdefault(key, {"cpu_m": 0, "memory_mib": 0, "pods": 0})
            slot["cpu_m"] += _parse_cpu(p["cpu_request"])
            slot["memory_mib"] += _parse_memory(p["memory_request"])
            slot["pods"] += 1
        top = sorted(by_dep.items(), key=lambda kv: kv[1]["cpu_m"], reverse=True)[:8]
        return {
            "namespace": namespace or "all",
            "pods": len(pods),
            "cpu_millicores": total_cpu,
            "cpu_cores": round(total_cpu / 1000, 2),
            "memory_mib": total_mem,
            "memory_gib": round(total_mem / 1024, 2),
            "by_namespace": by_ns,
            "top_workloads": [
                {"workload": k, **v} for k, v in top
            ],
        }

    def search(self, query: str, namespace: str | None = None) -> dict:
        q = query.lower()
        pods = [self._public_pod(p) for p in self.pods
                if q in p["name"].lower()
                and (namespace in (None, "all") or p["namespace"] == namespace)][:10]
        deps = [self._public_deployment(d) for d in self.deployments
                if q in d["name"].lower()
                and (namespace in (None, "all") or d["namespace"] == namespace)][:10]
        events = [
            {k: v for k, v in e.items() if k != "_ts"}
            for e in self.events
            if q in e["message"].lower() or q in e["reason"].lower()
            and (namespace in (None, "all") or e["namespace"] == namespace)
        ][:10]
        return {"pods": pods, "deployments": deps, "events": events}

    # -- mutating API (demo: simulated, state is updated in memory) -------
    def scale(self, name: str, namespace: str, replicas: int) -> dict:
        dep = next(
            (d for d in self.deployments
             if d["name"] == name and d["namespace"] == namespace),
            None,
        )
        if dep is None:
            return {"ok": False, "error": f'deployment "{name}" not found in namespace "{namespace}"'}
        before = dep["replicas"]["desired"]
        dep["replicas"].update({
            "desired": replicas, "ready": replicas,
            "updated": replicas, "available": replicas,
        })
        # Keep pods roughly in sync so the Pods view reflects the scale.
        owned = [p for p in self.pods if p["labels"]["app"] == name and p["namespace"] == namespace]
        while len(owned) < replicas:
            owned.append(self._pod(
                f"{name}-{self._suffix()}-{self._suffix()}",
                namespace, name, created=self._now,
            ))
            self.pods.append(owned[-1])
        while len(owned) > replicas:
            self.pods.remove(owned.pop())
        return {
            "ok": True, "deployment": name, "namespace": namespace,
            "replicas_before": before, "replicas_after": replicas,
            "demo": True,
        }

    def restart(self, name: str, namespace: str) -> dict:
        dep = next(
            (d for d in self.deployments
             if d["name"] == name and d["namespace"] == namespace),
            None,
        )
        if dep is None:
            return {"ok": False, "error": f'deployment "{name}" not found in namespace "{namespace}"'}
        restarted_at = self._now.isoformat()
        self._restarted_at[(namespace, name)] = restarted_at
        for p in self.pods:
            if p["labels"]["app"] == name and p["namespace"] == namespace:
                p["restarts"] += 1
        return {
            "ok": True, "deployment": name, "namespace": namespace,
            "restarted_at": restarted_at, "demo": True,
        }

    def rollback(self, name: str, namespace: str) -> dict:
        dep = next(
            (d for d in self.deployments
             if d["name"] == name and d["namespace"] == namespace),
            None,
        )
        if dep is None:
            return {"ok": False, "error": f'deployment "{name}" not found in namespace "{namespace}"'}
        if dep["revision"] <= 1:
            return {"ok": False, "error": f'no earlier revision found for deployment "{name}" (current revision: {dep["revision"]})'}
        before = dep["revision"]
        dep["revision"] -= 1
        history = self._history[(namespace, name)]
        history.insert(0, {
            "revision": before,
            "image": dep["images"][0],
            "created": self._now.isoformat(),
            "replicas": dep["replicas"]["desired"],
            "change": f"rolled back to revision {before - 1}",
        })
        return {
            "ok": True, "deployment": name, "namespace": namespace,
            "revision_before": before, "revision_after": before - 1,
            "demo": True,
        }
