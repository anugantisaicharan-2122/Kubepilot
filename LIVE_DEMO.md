# KubePilot — Live MCP Demo

Date: 2026-10-07. Ran the real MCP server over stdio and exercised it
with a small JSON-RPC client (throwaway harness, kept out of the repo).

## Setup

```bash
cd ~/workspace/projects/kubepilot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q        # 59 passed
```

## Demo run

Server started with `KUBEPILOT_READ_ONLY=true`, client sent
`initialize`, then these calls:

### 1. initialize -> server info

```json
{
  "server": {
    "name": "kubepilot",
    "version": ""
  },
  "protocol": "2024-11-05"
}
```

### 2. tools/list -> registered tools

```json
[
  "list_pods",
  "get_pod_logs",
  "list_deployments",
  "get_events",
  "describe_resource",
  "rollout_status",
  "restart_deployment",
  "rollback_deployment",
  "scale_deployment"
]
```

### 3. tools/call scale_deployment (KUBEPILOT_READ_ONLY=true)

```json
{
  "ok": false,
  "error": "refusing to scale: server is running in read-only mode (KUBEPILOT_READ_ONLY=true)"
}
```

### 4. tools/call list_pods (no cluster available)

```json
{
  "ok": false,
  "error": "ConfigException: Invalid kube-config file. No configuration found."
}
```

## Honest notes

- No Kubernetes cluster was available in this environment (no Docker
  daemon, so no local kind cluster), and `~/.kube/config` does not exist
  here. Cluster-backed calls therefore return the project's standard
  connection-error envelope — exactly the `{"ok": false, ...}` shape the
  tools are designed to produce when the API is unreachable.
- The guardrail behavior in step 3 is fully live: the mutating tool
  refused before touching any API client code.
- All 9 tools are registered and discoverable; the 6 read/write tools
  were previously covered by 44 unit tests, and the 3 new rollout
  tools added 15 more (59 passing total).
