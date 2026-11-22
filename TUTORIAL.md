# KubePilot Tutorial

A guided tour of KubePilot: what it is, how it works, what it can do,
where it fits, and how to use it — with the web dashboard and with an
AI agent. No prior MCP experience needed; basic Kubernetes familiarity
helps.

> **Try it without a cluster.** Every example below works in the
> dashboard's **demo mode** — realistic simulated data (94 pods,
> 15 deployments, 60 events across 4 namespaces). Start it with:
>
> ```bash
> kubepilot-dashboard --demo   # then open http://127.0.0.1:8000
> ```

---

## 1. How KubePilot works

### The idea in one paragraph

AI coding assistants are becoming operators, not just code generators.
But pointing an agent at a cluster with raw `kubectl` exec is how you
get a 3am page: no guardrails, no audit-friendly envelope, no
distinction between "look" and "touch". KubePilot is a small,
opinionated answer: a **Model Context Protocol (MCP) server** that
exposes everyday Kubernetes operations as **typed tools** an agent can
call — list pods, tail logs, read events, scale deployments — through
a discoverable interface, with safety enforced in code.

### The flow

```
You (plain English)
  → AI agent (Claude / Cursor / Copilot)
    → KubePilot MCP server (stdio, JSON-RPC)
      → Kubernetes API (official Python client)
```

1. **You ask in plain English.** "Why is the checkout API down in
   staging?" No kubectl, no YAML spelunking.
2. **The agent picks tools, not shell commands.** It calls
   `list_pods` and `get_pod_logs` instead of running
   `kubectl get pods | grep ...`. Every call is explicit and typed.
3. **Every answer comes back in one envelope.**
   `{"ok": true, ...}` on success, `{"ok": false, "error": "..."}` on
   failure. The agent always knows what happened.
4. **Guardrails are in code, not just docs.**
   `KUBEPILOT_READ_ONLY=true` makes mutating tools refuse to run, and
   `KUBEPILOT_ALLOWED_NAMESPACES` scopes every namespaced tool to an
   allow-list. A mistake in wording can't delete production.
5. **The dashboard is the human view of the same data.** Everything
   the agent sees — pods, deployments, logs, events, rollouts — is
   visible at http://127.0.0.1:8000, live. In demo mode it runs on
   simulated data; point it at a real cluster and the same pages show
   the truth.

### The two safety rules that matter

| Guardrail | What it does | How to set it |
|---|---|---|
| Read-only mode | All three mutating tools refuse with a clear error | `KUBEPILOT_READ_ONLY=true` |
| Namespace allow-list | Every namespaced tool is scoped to the namespaces you choose | `KUBEPILOT_ALLOWED_NAMESPACES=default,staging` |

Six of the nine tools are read-only by design — they physically
cannot change anything. The three that can change things refuse
unless you explicitly allow them.

### The JSON envelope

Every tool returns a JSON string shaped like one of these:

```json
{"ok": true, "namespace": "staging", "count": 3, "pods": [ ... ]}
```

```json
{"ok": false, "error": "namespace 'prod' is not in KUBEPILOT_ALLOWED_NAMESPACES (default,staging)"}
```

Agents (and the dashboard) never have to guess from free text whether
a call worked.

---

## 2. What KubePilot can do — the 9 tools

### Read-only tools (safe to call any time)

| Tool | What it does | Example |
|---|---|---|
| `list_pods` | List pods in a namespace, optional label selector; phase, readiness, restarts, age | `list_pods(namespace="staging", label_selector="app=checkout")` |
| `get_pod_logs` | Tail a pod's container logs (capped); `previous=true` reads the previous crashed instance | `get_pod_logs(pod_name="checkout-7d9f6b4c5-x2kq9", namespace="staging", tail_lines=80)` |
| `list_deployments` | Deployments with desired vs ready/updated/available replicas and images | `list_deployments(namespace="prod")` |
| `get_events` | Recent cluster events, newest first — scheduling, image-pull, probe failures | `get_events(namespace="prod", limit=50)` |
| `describe_resource` | Full manifest (JSON) of a pod, deployment, service, configmap, namespace or node | `describe_resource(kind="deployment", name="api", namespace="prod")` |
| `rollout_status` | Rollout progress with a `complete` / `in_progress` / `stalled` verdict | `rollout_status(name="api", namespace="prod")` |

### Mutating tools (refused in read-only mode)

| Tool | What it does | Example |
|---|---|---|
| `restart_deployment` | `kubectl rollout restart` equivalent — recreates pods via the `restartedAt` annotation | `restart_deployment(name="api", namespace="prod")` |
| `rollback_deployment` | `kubectl rollout undo` equivalent — restores the pod template from the newest older ReplicaSet | `rollback_deployment(name="api", namespace="prod")` |
| `scale_deployment` | Change a deployment's replica count; returns before/after counts | `scale_deployment(name="api", namespace="prod", replicas=5)` |

### Try-it flows in the dashboard

The **Tutorial** tab has a "Try it" button on every read-only tool —
it runs the real API call and shows the exact JSON the agent would
receive. The **Deployments** tab lets you select many deployments and
scale, restart or roll back in one go, with a per-item success/failure
report. The **Logs** tab reproduces the crash-loop debugging flow:
pick the `payments-worker` pod, check "Previous (crashed) instance",
and you will see the OOMKilled lines.

---

## 3. Guided walkthrough: the 3am incident

Follow along in demo mode. The scenario: checkout is down in prod.

**Step 1 — See the blast radius (Overview).** The Overview tab shows
94 pods, 1 CrashLoopBackOff, 1 Failed, 2 degraded deployments, and a
handful of warning events. The "Needs attention" panel names the
problems before you go looking.

**Step 2 — Find the sick pod (Pods).** Filter status to
`CrashLoopBackOff`. One pod: a `payments-worker` pod, 0/2 ready,
14 restarts. Click **Logs**.

**Step 3 — Read the previous instance (Logs).** Check "Previous
(crashed) instance" and fetch. The log ends with `FATAL … out of
memory (OOMKilled) — container exceeded 256Mi limit`, exit code 137.
The container isn't crashing randomly — it's being killed for memory.

**Step 4 — Check the events (Events).** Filter type to `Warning`.
You will see `OOMKilling` for the same pod and `FailedScheduling`
for `inventory-sync` (0/3 nodes have enough CPU). Two different
problems, one view.

**Step 5 — Check the rollout (Deployments).** `payments-worker` shows
2/3 ready, verdict `in_progress`; `inventory-sync` shows 0/1,
verdict `stalled`. Click **History** on `payments-worker` to see its
revision list before deciding whether a rollback is even possible.

**Step 6 — Decide, don't guess.** The evidence says: raise the memory
limit on `payments-worker` (a spec change, not a restart — restarting
a pod that OOMs just OOMs again). That is exactly the kind of
conclusion an agent reaches when it has the same three calls you
just made.

---

## 4. Where KubePilot can be used

| Industry / team | How it fits |
|---|---|
| **Platform engineering** | Give every developer a safe, typed way to inspect the platform without handing out kubeconfig. |
| **DevOps & SRE** | Faster incident triage: pods, logs and events in one question instead of five kubectl commands. |
| **SaaS** | Multi-tenant namespaces per customer or environment, scoped by the allow-list. |
| **Fintech** | Read-only by default for audit-heavy environments; mutations stay human-approved. |
| **Healthcare** | Inspect workloads without exposing patient data — manifests and summaries only, no secrets in output. |
| **E-commerce** | Scale checkout and search before a sale, roll back a bad deploy in one call. |
| **Media & streaming** | Watch transcode and delivery workers, catch OOM kills before viewers do. |
| **Telecom & gaming** | High-churn, high-replica services where "which pods are actually ready?" is asked all day. |

It works anywhere `kubectl` works: a laptop with a kubeconfig, a pod
running in-cluster with a service account, or a container.

---

## 5. How useful it is — concretely

- **No kubectl copy-paste.** The agent calls tools; you stop pasting
  terminal output into chat. A triage that used to be five commands
  and three pastes is one question.
- **Blast radius is limited by design.** Namespace allow-list +
  read-only mode are enforced in code, not in a runbook people forget.
- **Safe defaults.** Six of nine tools can't change anything; the
  three that can refuse unless explicitly allowed — and every mutation
  returns before/after state so the change is confirmable.
- **Faster incident triage.** Pods → logs → events is one
  conversation. The demo incident above takes about two minutes to
  work through by hand, and an agent does it in one turn.
- **Auditable.** Every tool call is a discrete, named operation with
  a predictable result envelope — much easier to review than a shell
  history full of pipes.
- **Bulk operations at scale.** The dashboard pages and filters
  server-side (never dumps a whole cluster into the page), and bulk
  scale / restart / rollback handle up to 100 deployments per request
  with a per-item report — so a fleet-wide rollout restart is one
  action, not a hundred.
- **Exportable.** Pods, deployments and events export as JSON or CSV
  for tickets, postmortems and audits.

---

## 6. The dashboard (KubePilot Pro)

```bash
kubepilot-dashboard                 # auto-detect: live if a cluster is reachable, else demo
kubepilot-dashboard --demo          # force demo mode (simulated data)
kubepilot-dashboard --live          # force live mode
kubepilot-dashboard --port 8000 --host 127.0.0.1
```

| Page | What you get |
|---|---|
| **Overview** | Stat cards, pods-by-status totals, CPU/memory request totals with per-namespace bars, "needs attention" list |
| **Pods** | Search, status + label filters, server-side pagination (10/20/50/100 per page), JSON/CSV export, per-pod Logs and Describe |
| **Deployments** | Multi-select + bulk scale/restart/rollback with per-item report, rollout verdicts, replica bars, rollout **history** modal, Describe |
| **Logs** | Pod picker, container, tail lines, previous-instance toggle, follow mode |
| **Events** | Timeline, type filter, search, pagination, export |
| **Tutorial** | This guide in-app, with live Try-it buttons |

Auto-refresh polls every 5 seconds (toggleable). The header badge
shows **LIVE** (green) or **DEMO** (amber) and a **READ-ONLY** badge
when mutations are disabled. Everything is served locally; no data
leaves your machine, and the page has no external assets.

### API reference (the dashboard's own JSON API)

All endpoints return `{"ok": true, ...}` or `{"ok": false, "error": "..."}`.

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Mode (live/demo), version, read-only flag, namespaces |
| `GET /api/overview?namespace=` | Totals by status, deployments, warning events, attention list |
| `GET /api/pods?namespace=&status=&search=&label_selector=&page=&page_size=` | Paginated, filtered pod list |
| `GET /api/deployments?namespace=&search=&page=&page_size=` | Paginated deployment list |
| `GET /api/events?namespace=&type=&search=&page=&page_size=` | Paginated event timeline |
| `GET /api/logs?pod=&namespace=&container=&tail_lines=&previous=` | Pod logs |
| `GET /api/rollout?name=&namespace=` | Rollout verdict |
| `GET /api/rollout-history?name=&namespace=` | Revision history |
| `GET /api/resources?namespace=` | CPU/memory request totals + top workloads |
| `GET /api/search?q=&namespace=` | Fast search across pods, deployments, events |
| `GET /api/describe?kind=&name=&namespace=` | Resource manifest |
| `GET /api/export?kind=pods\|deployments\|events&format=json\|csv&...` | Bulk export (up to 5,000 rows) |
| `POST /api/scale`, `/api/restart`, `/api/rollback` | Single deployment mutation |
| `POST /api/bulk/scale`, `/api/bulk/restart`, `/api/bulk/rollback` | Bulk mutation: `{"items": [{"namespace", "name", "replicas"?}]}` → per-item results |

---

## 7. Connecting a real cluster

```bash
export KUBEPILOT_KUBECONFIG=~/.kube/config   # or KUBEPILOT_IN_CLUSTER=true in a pod
export KUBEPILOT_READ_ONLY=true              # recommended for investigating
export KUBEPILOT_ALLOWED_NAMESPACES=default,staging
kubepilot-dashboard --port 8000
# open http://127.0.0.1:8000 — the badge switches from DEMO to LIVE
```

### Connect an AI agent (Claude Desktop example)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kubepilot": {
      "command": "/absolute/path/to/kubepilot/.venv/bin/python",
      "args": ["-m", "kubepilot"],
      "env": {
        "KUBEPILOT_KUBECONFIG": "/home/you/.kube/config",
        "KUBEPILOT_READ_ONLY": "true",
        "KUBEPILOT_ALLOWED_NAMESPACES": "default,staging"
      }
    }
  }
}
```

### Full configuration

| Variable | Default | Purpose |
|---|---|---|
| `KUBEPILOT_KUBECONFIG` | `~/.kube/config` | Path to kubeconfig |
| `KUBEPILOT_IN_CLUSTER` | `false` | Use pod service-account auth instead of kubeconfig |
| `KUBEPILOT_ALLOWED_NAMESPACES` | *(unset = all)* | Comma-separated allow-list, e.g. `default,staging` |
| `KUBEPILOT_READ_ONLY` | `false` | When `true`, mutating tools refuse to run |
| `KUBEPILOT_DEFAULT_NAMESPACE` | `default` | Default namespace for tool arguments |
| `KUBEPILOT_MAX_LOG_LINES` | `200` | Cap for `get_pod_logs` tail |
| `KUBEPILOT_LOG_LEVEL` | `INFO` | Python log level |
| `KUBEPILOT_DASHBOARD_DEMO` | *(unset = auto)* | `1` forces dashboard demo mode, `0` forces live |

### Docker

```bash
docker build -t kubepilot:latest .
docker run -i --rm \
  -v ~/.kube/config:/root/.kube/config:ro \
  -e KUBEPILOT_READ_ONLY=true \
  kubepilot:latest
```

---

## 8. Development & tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q        # 147 tests, no cluster needed
python -m compileall -q src/      # syntax check
```

The dashboard adds `src/kubepilot/dashboard.py` (HTTP + JSON API),
`src/kubepilot/dashboard_ui.py` (the single-page app),
`src/kubepilot/demo_data.py` (deterministic demo cluster) and
`tests/test_dashboard.py` (61 tests). `server.py`, `config.py` and
`k8s.py` are untouched — the MCP server's behavior, tool names, env
vars and existing tests are unchanged.
