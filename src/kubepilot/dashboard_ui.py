"""HTML/CSS/JS for the KubePilot Pro dashboard (single self-contained page).

No external assets: everything is inline so the dashboard works offline
and behind firewalls. Dark "pro" theme, top navigation, live polling,
bulk actions, export, and an in-app tutorial.
"""

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KubePilot Pro — Kubernetes Dashboard</title>
<style>
:root{
  --bg:#0b0f14; --panel:#111826; --panel2:#151e2e; --border:#1f2a3d; --border2:#2a3a52;
  --text:#e6edf3; --muted:#8b98a9; --muted2:#6b7a8d;
  --accent:#38bdf8; --accent2:#818cf8; --green:#22c55e; --amber:#f59e0b;
  --red:#ef4444; --red-bg:#2a1215; --green-bg:#0f2417; --amber-bg:#2a1f0a;
  --mono:ui-monospace,'SF Mono',SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
code{font-family:var(--mono);font-size:12.5px;background:#0d1420;border:1px solid var(--border);
  padding:1px 5px;border-radius:4px}
pre{font-family:var(--mono);font-size:12.5px;background:#0d1420;border:1px solid var(--border);
  border-radius:8px;padding:12px;overflow:auto;white-space:pre-wrap;word-break:break-word}
h1{font-size:20px;margin:0} h2{font-size:16px;margin:0 0 10px} h3{font-size:14px;margin:0 0 8px}
.muted{color:var(--muted)} .small{font-size:12px}
/* header */
header{position:sticky;top:0;z-index:50;background:rgba(11,15,20,.96);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--border)}
.header-in{max-width:1280px;margin:0 auto;padding:10px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;letter-spacing:.2px}
.brand .logo{width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,#0ea5e9,#6366f1);
  display:flex;align-items:center;justify-content:center;font-size:16px}
.brand .pro{font-size:10px;font-weight:700;color:#0b0f14;background:var(--accent);
  border-radius:4px;padding:2px 6px;letter-spacing:.6px}
nav{display:flex;gap:2px;flex-wrap:wrap}
nav button{background:none;border:0;color:var(--muted);font:inherit;font-weight:600;
  padding:7px 12px;border-radius:7px;cursor:pointer}
nav button:hover{color:var(--text);background:var(--panel2)}
nav button.active{color:#fff;background:#1c2a41}
.header-right{margin-left:auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.search-box{display:flex;align-items:center;gap:6px;background:var(--panel);border:1px solid var(--border);
  border-radius:8px;padding:6px 10px}
.search-box input{background:none;border:0;outline:0;color:var(--text);font:inherit;width:170px}
.search-box input::placeholder{color:var(--muted2)}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
  padding:4px 10px;border-radius:999px;border:1px solid var(--border2);background:var(--panel)}
.badge .dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green)}
.badge.demo .dot{background:var(--amber);box-shadow:0 0 6px var(--amber)}
.badge.ro .dot{background:var(--amber);box-shadow:none}
.badge.err .dot{background:var(--red);box-shadow:0 0 6px var(--red)}
select,input[type=text],input[type=number]{background:var(--panel);border:1px solid var(--border);
  color:var(--text);font:inherit;border-radius:8px;padding:7px 10px}
select:focus,input:focus{outline:1px solid var(--accent)}
button.btn{background:#1c2a41;border:1px solid var(--border2);color:var(--text);font:inherit;
  font-weight:600;padding:7px 14px;border-radius:8px;cursor:pointer}
button.btn:hover{background:#243650}
button.btn.primary{background:#0369a1;border-color:#0284c7;color:#fff}
button.btn.primary:hover{background:#0284c7}
button.btn.danger{background:#3f1215;border-color:#7f1d1d;color:#fca5a5}
button.btn:disabled{opacity:.45;cursor:not-allowed}
button.btn.sm{padding:4px 9px;font-size:12.5px}
/* layout */
main{max-width:1280px;margin:0 auto;padding:20px}
section.page{display:none}
section.page.active{display:block}
.banner{border:1px solid #7c5a10;background:var(--amber-bg);border-radius:10px;
  padding:12px 16px;margin-bottom:18px}
.banner b{color:#fcd34d}
.grid{display:grid;gap:14px}
.grid.c4{grid-template-columns:repeat(4,1fr)}
.grid.c3{grid-template-columns:repeat(3,1fr)}
.grid.c2{grid-template-columns:repeat(2,1fr)}
@media(max-width:900px){.grid.c4,.grid.c3{grid-template-columns:repeat(2,1fr)}.grid.c2{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px}
.card h2{margin-bottom:4px}
.stat .num{font-size:28px;font-weight:800;line-height:1.1}
.stat .lbl{color:var(--muted);font-size:12.5px;margin-top:4px}
.stat .sub{font-size:12px;color:var(--muted2);margin-top:6px}
/* tables */
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.toolbar .spacer{flex:1}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:600;padding:8px 10px;border-bottom:1px solid var(--border);
  white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:hover td{background:#131c2b}
.pill{display:inline-block;font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:999px}
.pill.green{background:var(--green-bg);color:#4ade80}
.pill.amber{background:var(--amber-bg);color:#fbbf24}
.pill.red{background:var(--red-bg);color:#f87171}
.pill.grey{background:#1c2534;color:#9aa7b8}
.pill.blue{background:#0e2238;color:#7dd3fc}
.bar{height:8px;background:#1c2534;border-radius:4px;overflow:hidden;min-width:90px}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,#0ea5e9,#22c55e);border-radius:4px}
.bar.warn>i{background:linear-gradient(90deg,#f59e0b,#ef4444)}
.pager{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
.pager .info{color:var(--muted);font-size:12.5px}
/* logs */
.logbox{background:#070b10;border:1px solid var(--border);border-radius:10px;padding:12px;
  font-family:var(--mono);font-size:12px;line-height:1.6;max-height:480px;overflow:auto;white-space:pre-wrap}
.logbox .err{color:#f87171}.logbox .warn{color:#fbbf24}.logbox .ok{color:#4ade80}
/* timeline */
.timeline{list-style:none;margin:0;padding:0}
.timeline li{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)}
.timeline .t{color:var(--muted);font-size:12px;white-space:nowrap;padding-top:2px;min-width:86px}
.timeline .b{flex:1}
/* tutorial */
.step{display:flex;gap:14px;margin-bottom:14px}
.step .n{flex:0 0 30px;height:30px;border-radius:50%;background:#0e2238;border:1px solid var(--border2);
  display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--accent)}
.toolgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:900px){.toolgrid{grid-template-columns:1fr}}
.tool{background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:12px}
.tool .kind{font-size:11px;font-weight:700;letter-spacing:.4px;text-transform:uppercase}
.tool .kind.ro{color:#4ade80}.tool .kind.mut{color:#fbbf24}
.industry{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:900px){.industry{grid-template-columns:repeat(2,1fr)}}
.ind{background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:12px}
.ind .ic{font-size:20px}
.diagram{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:center;padding:14px 0}
.diagram .node{background:#0e2238;border:1px solid var(--border2);border-radius:10px;padding:10px 14px;
  text-align:center;font-weight:600}
.diagram .node small{display:block;color:var(--muted);font-weight:400;font-size:11.5px}
.diagram .arr{color:var(--muted);font-size:18px}
/* modal + toast */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.65);display:none;align-items:flex-start;
  justify-content:center;z-index:100;padding:40px 16px}
.modal-bg.open{display:flex}
.modal{background:var(--panel);border:1px solid var(--border2);border-radius:12px;max-width:860px;
  width:100%;max-height:82vh;overflow:auto;padding:20px}
.modal h2{margin-bottom:12px}
#toasts{position:fixed;right:16px;bottom:16px;z-index:200;display:flex;flex-direction:column;gap:8px}
.toast{background:var(--panel2);border:1px solid var(--border2);border-left:4px solid var(--accent);
  border-radius:8px;padding:10px 14px;max-width:380px;box-shadow:0 8px 24px rgba(0,0,0,.5)}
.toast.err{border-left-color:var(--red)}
.toast.ok{border-left-color:var(--green)}
.spin{display:inline-block;width:12px;height:12px;border:2px solid var(--border2);
  border-top-color:var(--accent);border-radius:50%;animation:sp 0.8s linear infinite;vertical-align:-1px}
@keyframes sp{to{transform:rotate(360deg)}}
.bulkbar{display:none;align-items:center;gap:10px;background:#0e2238;border:1px solid var(--border2);
  border-radius:10px;padding:10px 12px;margin-bottom:12px;flex-wrap:wrap}
.bulkbar.show{display:flex}
footer{max-width:1280px;margin:0 auto;padding:16px 20px 30px;color:var(--muted2);font-size:12px}
kbd{font-family:var(--mono);background:#0d1420;border:1px solid var(--border);border-radius:4px;padding:0 5px}
</style>
</head>
<body>
<header>
  <div class="header-in">
    <div class="brand"><span class="logo">☸️</span> KubePilot <span class="pro">PRO</span></div>
    <nav id="nav">
      <button data-page="overview" class="active">Overview</button>
      <button data-page="pods">Pods</button>
      <button data-page="deployments">Deployments</button>
      <button data-page="logs">Logs</button>
      <button data-page="events">Events</button>
      <button data-page="tutorial">Tutorial</button>
    </nav>
    <div class="header-right">
      <div class="search-box">🔍 <input id="global-search" type="text" placeholder="Search pods, deployments, events…" aria-label="Search cluster"></div>
      <select id="ns-select" aria-label="Namespace"></select>
      <span class="badge" id="mode-badge"><span class="dot"></span><span id="mode-text">Connecting…</span></span>
      <span class="badge ro" id="ro-badge" style="display:none">READ-ONLY</span>
      <label class="small muted" title="Auto-refresh every 5 seconds"><input type="checkbox" id="autorefresh" checked> Auto-refresh</label>
    </div>
  </div>
</header>

<main>
  <div class="banner" id="demo-banner" style="display:none">
    <b>DEMO MODE — no cluster connected.</b>
    <span class="muted">You are looking at realistic simulated data (94 pods, 15 deployments, 60 events across 4 namespaces).
    Bulk actions, scaling and rollbacks work against the simulation. To connect a real cluster, set
    <code>KUBEPILOT_KUBECONFIG</code> to your kubeconfig (or run in-cluster with
    <code>KUBEPILOT_IN_CLUSTER=true</code>) and restart the dashboard — it will switch to LIVE mode automatically.</span>
  </div>

  <!-- OVERVIEW -->
  <section class="page active" id="page-overview">
    <div class="grid c4" id="stat-cards"></div>
    <div class="grid c2" style="margin-top:14px">
      <div class="card">
        <h2>Resource requests</h2>
        <p class="muted small" style="margin:0 0 10px">Sum of CPU / memory <i>requests</i> across all pods in scope — what the cluster has promised to workloads.</p>
        <div id="resource-panel"><span class="spin"></span> Loading…</div>
      </div>
      <div class="card">
        <h2>Pods by status</h2>
        <p class="muted small" style="margin:0 0 10px">Totals across the selected namespace scope.</p>
        <div id="status-panel"><span class="spin"></span> Loading…</div>
      </div>
    </div>
    <div class="card" style="margin-top:14px">
      <h2>Needs attention</h2>
      <p class="muted small" style="margin:0 0 10px">Warning events and non-running pods, newest first.</p>
      <div id="attention-panel"><span class="spin"></span> Loading…</div>
    </div>
  </section>

  <!-- PODS -->
  <section class="page" id="page-pods">
    <div class="card">
      <h2>Pods <span class="muted small" id="pods-total"></span></h2>
      <div class="toolbar">
        <input type="text" id="pods-search" placeholder="Search by name…" style="min-width:200px">
        <select id="pods-status">
          <option value="">All statuses</option>
          <option>Running</option><option>Pending</option><option>Failed</option>
          <option>Succeeded</option><option>CrashLoopBackOff</option><option>Unknown</option>
        </select>
        <input type="text" id="pods-label" placeholder="Label selector, e.g. app=checkout-api" style="min-width:220px">
        <select id="pods-pagesize"><option>10</option><option selected>20</option><option>50</option><option>100</option></select>
        <span class="spacer"></span>
        <button class="btn sm" id="pods-export-json">Export JSON</button>
        <button class="btn sm" id="pods-export-csv">Export CSV</button>
        <button class="btn sm primary" id="pods-refresh">Refresh</button>
      </div>
      <div id="pods-table-wrap"><span class="spin"></span> Loading pods…</div>
      <div class="pager">
        <button class="btn sm" id="pods-prev">← Prev</button>
        <span class="info" id="pods-pageinfo"></span>
        <button class="btn sm" id="pods-next">Next →</button>
      </div>
    </div>
  </section>

  <!-- DEPLOYMENTS -->
  <section class="page" id="page-deployments">
    <div class="card">
      <h2>Deployments <span class="muted small" id="deps-total"></span></h2>
      <div class="toolbar">
        <input type="text" id="deps-search" placeholder="Search by name…" style="min-width:200px">
        <select id="deps-pagesize"><option>10</option><option selected>20</option><option>50</option><option>100</option></select>
        <span class="spacer"></span>
        <button class="btn sm" id="deps-export-json">Export JSON</button>
        <button class="btn sm" id="deps-export-csv">Export CSV</button>
        <button class="btn sm primary" id="deps-refresh">Refresh</button>
      </div>
      <div class="bulkbar" id="bulkbar">
        <b id="bulk-count">0 selected</b>
        <label>Scale to <input type="number" id="bulk-replicas" min="0" max="50" value="3" style="width:64px"></label>
        <button class="btn sm primary" id="bulk-scale">Scale selected</button>
        <button class="btn sm" id="bulk-restart">Restart selected</button>
        <button class="btn sm danger" id="bulk-rollback">Rollback selected</button>
        <button class="btn sm" id="bulk-clear">Clear selection</button>
        <span class="muted small">Mutations are refused in read-only mode.</span>
      </div>
      <div id="bulk-report"></div>
      <div id="deps-table-wrap"><span class="spin"></span> Loading deployments…</div>
      <div class="pager">
        <button class="btn sm" id="deps-prev">← Prev</button>
        <span class="info" id="deps-pageinfo"></span>
        <button class="btn sm" id="deps-next">Next →</button>
      </div>
    </div>
  </section>

  <!-- LOGS -->
  <section class="page" id="page-logs">
    <div class="card">
      <h2>Pod logs</h2>
      <div class="toolbar">
        <select id="logs-pod" style="min-width:320px"></select>
        <input type="text" id="logs-container" placeholder="Container (optional)">
        <label class="small muted">Tail <input type="number" id="logs-tail" min="1" max="200" value="100" style="width:70px"></label>
        <label class="small muted"><input type="checkbox" id="logs-previous"> Previous (crashed) instance</label>
        <button class="btn sm primary" id="logs-fetch">Fetch logs</button>
        <label class="small muted"><input type="checkbox" id="logs-follow"> Follow (auto-refresh)</label>
      </div>
      <div class="logbox" id="logs-output">Pick a pod and press “Fetch logs”. In demo mode, try the crash-looping
<code>payments-worker</code> pod with “Previous instance” checked — you will see the OOMKilled lines.</div>
    </div>
  </section>

  <!-- EVENTS -->
  <section class="page" id="page-events">
    <div class="card">
      <h2>Event timeline</h2>
      <div class="toolbar">
        <select id="events-type"><option value="">All types</option><option>Normal</option><option>Warning</option></select>
        <input type="text" id="events-search" placeholder="Search reason / message…" style="min-width:220px">
        <select id="events-pagesize"><option selected>20</option><option>50</option><option>100</option></select>
        <span class="spacer"></span>
        <button class="btn sm" id="events-export-json">Export JSON</button>
        <button class="btn sm" id="events-export-csv">Export CSV</button>
        <button class="btn sm primary" id="events-refresh">Refresh</button>
      </div>
      <ul class="timeline" id="events-list"><li><span class="spin"></span> Loading events…</li></ul>
      <div class="pager">
        <button class="btn sm" id="events-prev">← Prev</button>
        <span class="info" id="events-pageinfo"></span>
        <button class="btn sm" id="events-next">Next →</button>
      </div>
    </div>
  </section>

  <!-- TUTORIAL -->
  <section class="page" id="page-tutorial">
    <div class="card">
      <h2>How KubePilot works</h2>
      <div class="diagram">
        <div class="node">👤 You<small>plain English</small></div><span class="arr">→</span>
        <div class="node">🤖 AI agent<small>Claude / Cursor / Copilot</small></div><span class="arr">→</span>
        <div class="node">☸️ KubePilot<small>MCP server · 9 tools</small></div><span class="arr">→</span>
        <div class="node">⎈ Kubernetes API<small>your cluster</small></div>
      </div>
      <div class="step"><div class="n">1</div><div><b>You ask in plain English.</b> “Why is the checkout API down in staging?”
      No kubectl, no YAML spelunking — just describe the symptom.</div></div>
      <div class="step"><div class="n">2</div><div><b>The agent picks tools, not shell commands.</b> It calls typed tools
      like <code>list_pods</code> and <code>get_pod_logs</code> instead of running raw <code>kubectl</code> — every call is
      explicit, logged, and shaped the same way.</div></div>
      <div class="step"><div class="n">3</div><div><b>Every answer comes back in one envelope.</b>
      <code>{"ok": true, ...}</code> on success, <code>{"ok": false, "error": "..."}</code> on failure — the agent
      always knows what happened and never has to guess from free text.</div></div>
      <div class="step"><div class="n">4</div><div><b>Guardrails are in code, not just docs.</b>
      <code>KUBEPILOT_READ_ONLY=true</code> makes mutating tools refuse to run, and
      <code>KUBEPILOT_ALLOWED_NAMESPACES</code> scopes every namespaced tool to an allow-list. A mistake in
      wording can’t delete production.</div></div>
      <div class="step"><div class="n">5</div><div><b>This dashboard is the human view of the same data.</b> Everything the
      agent sees — pods, deployments, logs, events, rollouts — is visible here, live. In demo mode it runs on
      simulated data; point it at a real cluster and the same pages show the truth.</div></div>
    </div>

    <div class="card" style="margin-top:14px">
      <h2>The 9 tools — try them live</h2>
      <p class="muted small" style="margin:0 0 12px">Read-only tools run against the current namespace scope. “Try it” executes the real API call and shows the JSON the agent would receive.</p>
      <div class="toolgrid" id="tool-grid"></div>
      <div id="try-output" style="margin-top:12px"></div>
    </div>

    <div class="card" style="margin-top:14px">
      <h2>Where KubePilot is used</h2>
      <div class="industry">
        <div class="ind"><div class="ic">🧑‍💻</div><b>Platform engineering</b><p class="muted small">Give every developer a safe, typed way to inspect the platform without handing out kubeconfig.</p></div>
        <div class="ind"><div class="ic">🚨</div><b>DevOps &amp; SRE</b><p class="muted small">Faster incident triage: pods, logs and events in one question instead of five kubectl commands.</p></div>
        <div class="ind"><div class="ic">☁️</div><b>SaaS</b><p class="muted small">Multi-tenant namespaces per customer or environment, scoped by the allow-list.</p></div>
        <div class="ind"><div class="ic">🏦</div><b>Fintech</b><p class="muted small">Read-only by default for audit-heavy environments; mutations stay human-approved.</p></div>
        <div class="ind"><div class="ic">🏥</div><b>Healthcare</b><p class="muted small">Inspect workloads without exposing patient data — manifests and summaries only, no secrets in output.</p></div>
        <div class="ind"><div class="ic">🛒</div><b>E-commerce</b><p class="muted small">Scale checkout and search before a sale, roll back a bad deploy in one call.</p></div>
        <div class="ind"><div class="ic">🎬</div><b>Media &amp; streaming</b><p class="muted small">Watch transcode and delivery workers, catch OOM kills before viewers do.</p></div>
        <div class="ind"><div class="ic">📡</div><b>Telecom &amp; gaming</b><p class="muted small">High-churn, high-replica services where “which pods are actually ready?” is asked all day.</p></div>
      </div>
    </div>

    <div class="card" style="margin-top:14px">
      <h2>Why it’s useful</h2>
      <ul>
        <li><b>No kubectl copy-paste.</b> The agent calls tools; you stop pasting terminal output into chat.</li>
        <li><b>Blast radius is limited by design.</b> Namespace allow-list + read-only mode are enforced in code.</li>
        <li><b>Safe defaults.</b> Six of the nine tools can’t change anything; the three that can refuse unless explicitly allowed.</li>
        <li><b>Faster incident triage.</b> Pods → logs → events is one conversation, not a runbook hunt.</li>
        <li><b>Auditable.</b> Every tool call is a discrete, named operation with a predictable result envelope.</li>
        <li><b>Works anywhere kubectl works.</b> Local kubeconfig, in-cluster service account, or Docker.</li>
      </ul>
    </div>

    <div class="card" style="margin-top:14px">
      <h2>Connect a real cluster</h2>
      <pre>export KUBEPILOT_KUBECONFIG=~/.kube/config   # or KUBEPILOT_IN_CLUSTER=true in a pod
export KUBEPILOT_READ_ONLY=true              # recommended for investigating
export KUBEPILOT_ALLOWED_NAMESPACES=default,staging
kubepilot-dashboard --port 8000
# open http://127.0.0.1:8000 — the badge switches from DEMO to LIVE</pre>
      <p class="muted small">Full walkthrough, tool reference and industry examples: <code>TUTORIAL.md</code> in the project root.</p>
    </div>
  </section>
</main>

<div class="modal-bg" id="modal-bg"><div class="modal" id="modal"></div></div>
<div id="toasts"></div>
<footer>KubePilot Pro · MCP server for Kubernetes · <span id="foot-mode">demo mode</span> · All data served by the local dashboard API — no data leaves your machine.</footer>
<script>
'use strict';
const state = {
  page: 'overview', namespace: 'all', mode: 'demo', readOnly: false,
  podsPage: 1, podsPageSize: 20, podsStatus: '', podsSearch: '', podsLabel: '',
  depsPage: 1, depsPageSize: 20, depsSearch: '', selectedDeps: new Set(),
  eventsPage: 1, eventsPageSize: 20, eventsType: '', eventsSearch: '',
  lastUpdated: null, podOptionsLoaded: false,
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtTime = (iso) => { try { return new Date(iso).toLocaleTimeString(); } catch(e){ return iso || ''; } };
const fmtAgo = (iso) => { if(!iso) return '—'; const s = Math.max(0, (Date.now() - new Date(iso).getTime())/1000);
  if (s < 60) return Math.floor(s) + 's ago'; if (s < 3600) return Math.floor(s/60) + 'm ago';
  if (s < 86400) return Math.floor(s/3600) + 'h ago'; return Math.floor(s/86400) + 'd ago'; };

function toast(msg, kind){
  const el = document.createElement('div');
  el.className = 'toast' + (kind ? ' ' + kind : '');
  el.textContent = msg;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

async function api(path, opts){
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch(e) { /* non-JSON (CSV export uses direct nav) */ }
  if (!res.ok) throw new Error((data && data.error) || ('HTTP ' + res.status));
  return data;
}

function setStatus(ok, label){
  const badge = $('mode-badge');
  badge.classList.toggle('err', !ok);
  $('mode-text').textContent = label;
}

async function loadStatus(){
  try {
    const s = await api('/api/status');
    state.mode = s.mode; state.readOnly = !!s.read_only;
    setStatus(true, s.mode === 'live' ? '● LIVE' : '● DEMO');
    $('mode-badge').classList.toggle('demo', s.mode !== 'live');
    $('demo-banner').style.display = s.mode === 'demo' ? '' : 'none';
    $('foot-mode').textContent = s.mode === 'demo' ? 'demo mode — simulated data' : 'live mode — connected to your cluster';
    $('ro-badge').style.display = s.read_only ? '' : 'none';
    if (s.namespaces) fillNamespaces(s.namespaces);
  } catch(e){ setStatus(false, 'API unreachable'); }
}

function fillNamespaces(list){
  const sel = $('ns-select');
  const cur = sel.value || 'all';
  sel.innerHTML = '<option value="all">All namespaces</option>' +
    list.map((n) => '<option value="' + esc(n) + '">' + esc(n) + '</option>').join('');
  sel.value = list.includes(cur) ? cur : 'all';
  state.namespace = sel.value;
}

function nsParam(){ return state.namespace === 'all' ? '' : '&namespace=' + encodeURIComponent(state.namespace); }
function nsQuery(){ return state.namespace === 'all' ? '' : '?namespace=' + encodeURIComponent(state.namespace); }

function pillFor(status){
  const map = {Running:'green', Succeeded:'green', complete:'green',
    Pending:'amber', CrashLoopBackOff:'red', Failed:'red', Unknown:'grey',
    in_progress:'amber', stalled:'red'};
  return '<span class="pill ' + (map[status] || 'grey') + '">' + esc(status) + '</span>';
}
function verdictPill(v){ return pillFor(v); }

/* ---------------- Overview ---------------- */
async function loadOverview(){
  try {
    const [ov, res] = await Promise.all([
      api('/api/overview' + nsQuery()),
      api('/api/resources' + nsQuery()),
    ]);
    const p = ov.pods, d = ov.deployments;
    $('stat-cards').innerHTML =
      statCard('Pods', p.total, p.running + ' running · ' + p.not_ready + ' not ready', p.failed ? p.failed + ' failed' : 'all healthy') +
      statCard('Deployments', d.total, d.ready + ' fully ready', d.degraded ? d.degraded + ' degraded' : 'all ready') +
      statCard('Restarts', p.restarts, 'across all pods', p.restarts > 10 ? 'check crash-looping pods' : 'within normal range') +
      statCard('Warning events', ov.warning_events, 'in the selected scope', ov.warning_events ? 'see Events tab' : 'nothing alarming');
    const maxCpu = Math.max(1, ...Object.values(res.by_namespace).map((v) => v.cpu_m));
    $('resource-panel').innerHTML =
      '<div style="display:flex;justify-content:space-between"><span>Total CPU requests</span><b>' + res.cpu_cores + ' cores</b></div>' +
      '<div style="display:flex;justify-content:space-between"><span>Total memory requests</span><b>' + res.memory_gib + ' GiB</b></div>' +
      '<div style="margin-top:10px">' + Object.entries(res.by_namespace).map(([ns, v]) =>
        '<div style="margin-bottom:8px"><div class="small" style="display:flex;justify-content:space-between"><span>' + esc(ns) + ' · ' + v.pods + ' pods</span><span class="muted">' + (v.cpu_m/1000).toFixed(2) + ' cores · ' + (v.memory_mib/1024).toFixed(2) + ' GiB</span></div>' +
        '<div class="bar"><i style="width:' + Math.round(100*v.cpu_m/maxCpu) + '%"></i></div></div>').join('') + '</div>' +
      '<div class="small muted" style="margin-top:8px">Top workload: ' + esc(res.top_workloads[0] ? res.top_workloads[0].workload : '—') + '</div>';
    $('status-panel').innerHTML = Object.entries(p.by_status).map(([st, n]) =>
      '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)">' +
      '<span>' + pillFor(st) + '</span><b>' + n + '</b></div>').join('') +
      '<div class="small muted" style="margin-top:8px">Pods not ready: ' + p.not_ready + ' · Deployments degraded: ' + d.degraded + '</div>';
    const att = ov.attention || [];
    $('attention-panel').innerHTML = att.length ? att.map((a) =>
      '<div style="padding:8px 0;border-bottom:1px solid var(--border)"><b>' + esc(a.title) + '</b> ' +
      '<span class="muted small">' + esc(a.detail || '') + '</span><div class="small muted">' + fmtAgo(a.time) + '</div></div>').join('')
      : '<p class="muted">Nothing needs attention right now.</p>';
    state.lastUpdated = new Date();
  } catch(e){ $('stat-cards').innerHTML = '<div class="card">Failed to load overview: ' + esc(e.message) + '</div>'; }
}
function statCard(label, num, sub1, sub2){
  return '<div class="card stat"><div class="num">' + esc(num) + '</div><div class="lbl">' + esc(label) + '</div>' +
    '<div class="sub">' + esc(sub1) + '<br>' + esc(sub2) + '</div></div>';
}

/* ---------------- Pods ---------------- */
async function loadPods(){
  const q = new URLSearchParams({page: state.podsPage, page_size: state.podsPageSize});
  if (state.namespace !== 'all') q.set('namespace', state.namespace);
  if (state.podsStatus) q.set('status', state.podsStatus);
  if (state.podsSearch) q.set('search', state.podsSearch);
  if (state.podsLabel) q.set('label_selector', state.podsLabel);
  try {
    const d = await api('/api/pods?' + q.toString());
    $('pods-total').textContent = '· ' + d.total + ' pods';
    $('pods-pageinfo').textContent = 'Page ' + d.page + ' of ' + d.pages + ' · ' + d.total + ' total';
    $('pods-prev').disabled = d.page <= 1; $('pods-next').disabled = d.page >= d.pages;
    if (!d.items.length) { $('pods-table-wrap').innerHTML = '<p class="muted">No pods match the current filters.</p>'; return; }
    $('pods-table-wrap').innerHTML = '<table><thead><tr><th>Name</th><th>Namespace</th><th>Status</th><th>Ready</th><th>Restarts</th><th>Age</th><th>Node</th><th>CPU req</th><th>Mem req</th><th></th></tr></thead><tbody>' +
      d.items.map((p) => '<tr><td><code>' + esc(p.name) + '</code></td><td>' + esc(p.namespace) + '</td><td>' + pillFor(p.status || p.phase) + '</td>' +
        '<td>' + esc(p.ready) + '</td><td>' + esc(p.restarts) + '</td><td>' + esc(p.age) + '</td><td>' + esc(p.node || '—') + '</td>' +
        '<td>' + esc(p.cpu_request || '—') + '</td><td>' + esc(p.memory_request || '—') + '</td>' +
        '<td><button class="btn sm" data-logs="' + esc(p.name) + '" data-ns="' + esc(p.namespace) + '">Logs</button> ' +
        '<button class="btn sm" data-describe="pod:' + esc(p.name) + ':' + esc(p.namespace) + '">Describe</button></td></tr>').join('') +
      '</tbody></table>';
    state.lastUpdated = new Date();
  } catch(e){ $('pods-table-wrap').innerHTML = '<p style="color:#f87171">Failed to load pods: ' + esc(e.message) + '</p>'; }
}

/* ---------------- Deployments ---------------- */
async function loadDeployments(){
  const q = new URLSearchParams({page: state.depsPage, page_size: state.depsPageSize});
  if (state.namespace !== 'all') q.set('namespace', state.namespace);
  if (state.depsSearch) q.set('search', state.depsSearch);
  try {
    const d = await api('/api/deployments?' + q.toString());
    $('deps-total').textContent = '· ' + d.total + ' deployments';
    $('deps-pageinfo').textContent = 'Page ' + d.page + ' of ' + d.pages + ' · ' + d.total + ' total';
    $('deps-prev').disabled = d.page <= 1; $('deps-next').disabled = d.page >= d.pages;
    if (!d.items.length) { $('deps-table-wrap').innerHTML = '<p class="muted">No deployments match the current filters.</p>'; return; }
    $('deps-table-wrap').innerHTML = '<table><thead><tr><th></th><th>Name</th><th>Namespace</th><th>Replicas</th><th>Rollout</th><th>Images</th><th>Age</th><th></th></tr></thead><tbody>' +
      d.items.map((dep) => {
        const r = dep.replicas, pct = r.desired ? Math.round(100 * r.ready / r.desired) : 100;
        const checked = state.selectedDeps.has(dep.namespace + '/' + dep.name) ? 'checked' : '';
        return '<tr><td><input type="checkbox" class="dep-check" data-ns="' + esc(dep.namespace) + '" data-name="' + esc(dep.name) + '" ' + checked + '></td>' +
          '<td><code>' + esc(dep.name) + '</code></td><td>' + esc(dep.namespace) + '</td>' +
          '<td><div style="display:flex;align-items:center;gap:8px"><div class="bar' + (pct < 100 ? ' warn' : '') + '"><i style="width:' + pct + '%"></i></div><span>' + r.ready + '/' + r.desired + '</span></div></td>' +
          '<td>' + verdictPill(dep.verdict || 'complete') + '</td>' +
          '<td class="small">' + dep.images.map(esc).join('<br>') + '</td><td>' + esc(dep.age) + '</td>' +
          '<td style="white-space:nowrap"><button class="btn sm" data-history="' + esc(dep.namespace) + ':' + esc(dep.name) + '">History</button> ' +
          '<button class="btn sm" data-describe="deployment:' + esc(dep.name) + ':' + esc(dep.namespace) + '">Describe</button></td></tr>';
      }).join('') + '</tbody></table>';
    updateBulkBar();
    state.lastUpdated = new Date();
  } catch(e){ $('deps-table-wrap').innerHTML = '<p style="color:#f87171">Failed to load deployments: ' + esc(e.message) + '</p>'; }
}

function updateBulkBar(){
  const n = state.selectedDeps.size;
  $('bulkbar').classList.toggle('show', n > 0);
  $('bulk-count').textContent = n + ' selected';
  const dis = state.readOnly;
  ['bulk-scale','bulk-restart','bulk-rollback'].forEach((id) => { $(id).disabled = dis; });
  if (dis) $('bulk-count').textContent += ' · read-only mode: mutations disabled';
}

async function bulkAction(kind){
  const items = [...state.selectedDeps].map((key) => {
    const [namespace, name] = key.split('/');
    const it = {namespace, name};
    if (kind === 'scale') it.replicas = parseInt($('bulk-replicas').value, 10);
    return it;
  });
  if (!items.length) return;
  if (kind === 'scale' && (isNaN(items[0].replicas) || items[0].replicas < 0)) { toast('Replicas must be 0 or greater.', 'err'); return; }
  const verb = kind === 'scale' ? 'scale to ' + items[0].replicas : kind;
  if (!confirm('Bulk ' + verb + ' for ' + items.length + ' deployment(s)?')) return;
  try {
    const res = await api('/api/bulk/' + kind, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({items})});
    const ok = res.succeeded, bad = res.failed;
    $('bulk-report').innerHTML = '<div class="card" style="margin-bottom:12px"><h3>Bulk ' + esc(kind) + ': ' + ok + ' succeeded · ' + bad + ' failed</h3>' +
      '<table><thead><tr><th>Deployment</th><th>Result</th><th>Detail</th></tr></thead><tbody>' +
      res.results.map((r) => '<tr><td><code>' + esc(r.namespace + '/' + r.name) + '</code></td><td>' + (r.ok ? '<span class="pill green">ok</span>' : '<span class="pill red">failed</span>') + '</td><td class="small">' + esc(r.error || r.detail || '') + '</td></tr>').join('') +
      '</tbody></table></div>';
    toast('Bulk ' + kind + ': ' + ok + ' succeeded, ' + bad + ' failed.', bad ? 'err' : 'ok');
    state.selectedDeps.clear();
    loadDeployments(); loadOverview();
  } catch(e){ toast('Bulk ' + kind + ' failed: ' + e.message, 'err'); }
}

/* ---------------- Logs ---------------- */
async function loadPodOptions(){
  try {
    const d = await api('/api/pods?page=1&page_size=100' + nsParam());
    const sel = $('logs-pod');
    const cur = sel.value;
    sel.innerHTML = d.items.map((p) => '<option value="' + esc(p.namespace + '/' + p.name) + '">' + esc(p.namespace + '/' + p.name) + ' (' + esc(p.status || p.phase) + ')</option>').join('');
    if (cur) sel.value = cur;
    state.podOptionsLoaded = true;
  } catch(e){ /* leave selector empty; fetch will report the error */ }
}

async function fetchLogs(){
  const sel = $('logs-pod').value;
  if (!sel) { toast('No pod selected.', 'err'); return; }
  const [namespace, ...rest] = sel.split('/');
  const pod = rest.join('/');
  const q = new URLSearchParams({pod, namespace,
    container: $('logs-container').value,
    tail_lines: $('logs-tail').value,
    previous: $('logs-previous').checked ? 'true' : 'false'});
  $('logs-output').textContent = 'Loading logs…';
  try {
    const d = await api('/api/logs?' + q.toString());
    if (!d.ok) { $('logs-output').textContent = 'Error: ' + (d.error || 'unknown error'); return; }
    const lines = (d.logs || '(no log output)').split('\n');
    $('logs-output').innerHTML = lines.map((l) => {
      const cls = /ERROR|FATAL|OOM|failed/i.test(l) ? 'err' : /WARN/i.test(l) ? 'warn' : '';
      return '<span class="' + cls + '">' + esc(l) + '</span>';
    }).join('\n');
    $('logs-output').scrollTop = $('logs-output').scrollHeight;
  } catch(e){ $('logs-output').textContent = 'Failed to fetch logs: ' + e.message; }
}

/* ---------------- Events ---------------- */
async function loadEvents(){
  const q = new URLSearchParams({page: state.eventsPage, page_size: state.eventsPageSize});
  if (state.namespace !== 'all') q.set('namespace', state.namespace);
  if (state.eventsType) q.set('type', state.eventsType);
  if (state.eventsSearch) q.set('search', state.eventsSearch);
  try {
    const d = await api('/api/events?' + q.toString());
    $('events-pageinfo').textContent = 'Page ' + d.page + ' of ' + d.pages + ' · ' + d.total + ' total';
    $('events-prev').disabled = d.page <= 1; $('events-next').disabled = d.page >= d.pages;
    if (!d.items.length) { $('events-list').innerHTML = '<li class="muted">No events match the current filters.</li>'; return; }
    $('events-list').innerHTML = d.items.map((e) =>
      '<li><span class="t">' + fmtAgo(e.last_seen) + '</span><span class="b">' +
      (e.type === 'Warning' ? '<span class="pill amber">Warning</span>' : '<span class="pill blue">Normal</span>') +
      ' <b>' + esc(e.reason) + '</b> · <code>' + esc(e.object) + '</code>' +
      (e.count > 1 ? ' <span class="muted small">×' + e.count + '</span>' : '') +
      '<div class="muted">' + esc(e.message) + '</div></span></li>').join('');
    state.lastUpdated = new Date();
  } catch(e){ $('events-list').innerHTML = '<li style="color:#f87171">Failed to load events: ' + esc(e.message) + '</li>'; }
}

/* ---------------- Modal: history / describe ---------------- */
function openModal(html){ $('modal').innerHTML = html; $('modal-bg').classList.add('open'); }
function closeModal(){ $('modal-bg').classList.remove('open'); }
$('modal-bg').addEventListener('click', (e) => { if (e.target.id === 'modal-bg') closeModal(); });

async function showHistory(ns, name){
  openModal('<h2>Rollout history — ' + esc(ns + '/' + name) + '</h2><p class="muted"><span class="spin"></span> Loading…</p>');
  try {
    const d = await api('/api/rollout-history?name=' + encodeURIComponent(name) + '&namespace=' + encodeURIComponent(ns));
    if (!d.ok) { openModal('<h2>Rollout history</h2><p style="color:#f87171">' + esc(d.error || 'unknown error') + '</p><button class="btn" onclick="closeModal()">Close</button>'); return; }
    openModal('<h2>Rollout history — ' + esc(ns + '/' + name) + '</h2>' +
      '<table><thead><tr><th>Revision</th><th>Image</th><th>Created</th><th>Replicas</th><th>Change</th></tr></thead><tbody>' +
      d.history.map((h) => '<tr><td><b>#' + h.revision + '</b></td><td><code>' + esc(h.image) + '</code></td><td>' + fmtTime(h.created) + '</td><td>' + h.replicas + '</td><td class="small">' + esc(h.change || '') + '</td></tr>').join('') +
      '</tbody></table><p style="margin-top:12px"><button class="btn" onclick="closeModal()">Close</button></p>');
  } catch(e){ openModal('<h2>Rollout history</h2><p style="color:#f87171">' + esc(e.message) + '</p><button class="btn" onclick="closeModal()">Close</button>'); }
}

async function showDescribe(kind, name, ns){
  openModal('<h2>Describe ' + esc(kind) + ' / ' + esc(name) + '</h2><p class="muted"><span class="spin"></span> Loading…</p>');
  try {
    const d = await api('/api/describe?kind=' + encodeURIComponent(kind) + '&name=' + encodeURIComponent(name) + '&namespace=' + encodeURIComponent(ns));
    openModal('<h2>Describe ' + esc(kind) + ' / ' + esc(name) + '</h2><pre>' + esc(JSON.stringify(d, null, 2)) + '</pre><p><button class="btn" onclick="closeModal()">Close</button></p>');
  } catch(e){ openModal('<h2>Describe</h2><p style="color:#f87171">' + esc(e.message) + '</p><button class="btn" onclick="closeModal()">Close</button>'); }
}

/* ---------------- Tutorial try-it ---------------- */
const TOOLS = [
  {name:'list_pods', kind:'read-only', desc:'List pods in a namespace: phase, readiness, restarts, age.', try:'/api/pods?page=1&page_size=5'},
  {name:'get_pod_logs', kind:'read-only', desc:'Tail a pod’s container logs (capped). previous=true reads the crashed instance.', try:null},
  {name:'list_deployments', kind:'read-only', desc:'Deployments with desired vs ready/updated/available replicas and images.', try:'/api/deployments?page=1&page_size=5'},
  {name:'get_events', kind:'read-only', desc:'Recent cluster events, newest first — scheduling, image-pull, probe failures.', try:'/api/events?page=1&page_size=5'},
  {name:'describe_resource', kind:'read-only', desc:'Full manifest (JSON) of a pod, deployment, service, configmap, namespace or node.', try:null},
  {name:'rollout_status', kind:'read-only', desc:'Rollout progress with a complete / in_progress / stalled verdict.', try:null},
  {name:'restart_deployment', kind:'mutating', desc:'kubectl rollout restart equivalent — recreates pods with the same spec.', try:null},
  {name:'rollback_deployment', kind:'mutating', desc:'kubectl rollout undo equivalent — restores the newest older revision.', try:null},
  {name:'scale_deployment', kind:'mutating', desc:'Change a deployment’s replica count; returns before/after counts.', try:null},
];
function renderTools(){
  $('tool-grid').innerHTML = TOOLS.map((t) =>
    '<div class="tool"><div class="kind ' + (t.kind === 'read-only' ? 'ro' : 'mut') + '">' + t.kind + '</div>' +
    '<h3 style="margin:6px 0"><code>' + t.name + '</code></h3><p class="muted small" style="margin:0 0 10px">' + t.desc + '</p>' +
    (t.try ? '<button class="btn sm primary" data-try="' + t.try + '" data-tool="' + t.name + '">Try it →</button>'
           : '<span class="small muted">Try it from the Deployments or Logs tab.</span>') + '</div>').join('');
}
async function tryTool(path, name){
  $('try-output').innerHTML = '<pre>Running ' + esc(name) + '…</pre>';
  try {
    const d = await api(path + (path.includes('?') ? '&' : '?') + (state.namespace !== 'all' ? 'namespace=' + encodeURIComponent(state.namespace) : ''));
    $('try-output').innerHTML = '<h3>Result — <code>' + esc(name) + '</code></h3><pre>' + esc(JSON.stringify(d, null, 2).slice(0, 4000)) + '</pre>';
  } catch(e){ $('try-output').innerHTML = '<pre style="color:#f87171">Error: ' + esc(e.message) + '</pre>'; }
}

/* ---------------- Search ---------------- */
async function runGlobalSearch(q){
  if (!q.trim()) return;
  try {
    const d = await api('/api/search?q=' + encodeURIComponent(q) + (state.namespace !== 'all' ? '&namespace=' + encodeURIComponent(state.namespace) : ''));
    const rows = [];
    d.pods.forEach((p) => rows.push(['Pod', p.namespace + '/' + p.name, p.status || p.phase]));
    d.deployments.forEach((x) => rows.push(['Deployment', x.namespace + '/' + x.name, (x.replicas.ready) + '/' + (x.replicas.desired) + ' ready']));
    d.events.forEach((e) => rows.push(['Event', e.reason + ' — ' + e.object, e.message.slice(0, 80)]));
    openModal('<h2>Search results for “' + esc(q) + '”</h2>' +
      (rows.length ? '<table><thead><tr><th>Type</th><th>Match</th><th>Detail</th></tr></thead><tbody>' +
        rows.map((r) => '<tr><td>' + r[0] + '</td><td><code>' + esc(r[1]) + '</code></td><td class="small">' + esc(r[2]) + '</td></tr>').join('') + '</tbody></table>'
        : '<p class="muted">No matches.</p>') +
      '<p style="margin-top:12px"><button class="btn" onclick="closeModal()">Close</button></p>');
  } catch(e){ toast('Search failed: ' + e.message, 'err'); }
}

/* ---------------- Navigation & wiring ---------------- */
function showPage(page){
  state.page = page;
  document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  document.querySelectorAll('section.page').forEach((s) => s.classList.toggle('active', s.id === 'page-' + page));
  refreshCurrent();
}
function refreshCurrent(){
  if (state.page === 'overview') loadOverview();
  else if (state.page === 'pods') loadPods();
  else if (state.page === 'deployments') loadDeployments();
  else if (state.page === 'logs') { if (!state.podOptionsLoaded) loadPodOptions(); }
  else if (state.page === 'events') loadEvents();
}
document.querySelectorAll('#nav button').forEach((b) => b.addEventListener('click', () => showPage(b.dataset.page)));
$('ns-select').addEventListener('change', (e) => {
  state.namespace = e.target.value;
  state.podsPage = 1; state.depsPage = 1; state.eventsPage = 1; state.podOptionsLoaded = false;
  refreshCurrent();
});
$('global-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') runGlobalSearch(e.target.value); });

let debounce = null;
function debounced(fn){ clearTimeout(debounce); debounce = setTimeout(fn, 350); }
$('pods-search').addEventListener('input', (e) => debounced(() => { state.podsSearch = e.target.value; state.podsPage = 1; loadPods(); }));
$('pods-status').addEventListener('change', (e) => { state.podsStatus = e.target.value; state.podsPage = 1; loadPods(); });
$('pods-label').addEventListener('input', (e) => debounced(() => { state.podsLabel = e.target.value; state.podsPage = 1; loadPods(); }));
$('pods-pagesize').addEventListener('change', (e) => { state.podsPageSize = parseInt(e.target.value, 10); state.podsPage = 1; loadPods(); });
$('pods-prev').addEventListener('click', () => { if (state.podsPage > 1) { state.podsPage--; loadPods(); } });
$('pods-next').addEventListener('click', () => { state.podsPage++; loadPods(); });
$('pods-refresh').addEventListener('click', loadPods);
$('pods-export-json').addEventListener('click', () => exportData('pods', 'json'));
$('pods-export-csv').addEventListener('click', () => exportData('pods', 'csv'));

$('deps-search').addEventListener('input', (e) => debounced(() => { state.depsSearch = e.target.value; state.depsPage = 1; loadDeployments(); }));
$('deps-pagesize').addEventListener('change', (e) => { state.depsPageSize = parseInt(e.target.value, 10); state.depsPage = 1; loadDeployments(); });
$('deps-prev').addEventListener('click', () => { if (state.depsPage > 1) { state.depsPage--; loadDeployments(); } });
$('deps-next').addEventListener('click', () => { state.depsPage++; loadDeployments(); });
$('deps-refresh').addEventListener('click', loadDeployments);
$('deps-export-json').addEventListener('click', () => exportData('deployments', 'json'));
$('deps-export-csv').addEventListener('click', () => exportData('deployments', 'csv'));
$('bulk-scale').addEventListener('click', () => bulkAction('scale'));
$('bulk-restart').addEventListener('click', () => bulkAction('restart'));
$('bulk-rollback').addEventListener('click', () => bulkAction('rollback'));
$('bulk-clear').addEventListener('click', () => { state.selectedDeps.clear(); loadDeployments(); });

$('logs-fetch').addEventListener('click', fetchLogs);
$('logs-pod').addEventListener('change', fetchLogs);

$('events-type').addEventListener('change', (e) => { state.eventsType = e.target.value; state.eventsPage = 1; loadEvents(); });
$('events-search').addEventListener('input', (e) => debounced(() => { state.eventsSearch = e.target.value; state.eventsPage = 1; loadEvents(); }));
$('events-pagesize').addEventListener('change', (e) => { state.eventsPageSize = parseInt(e.target.value, 10); state.eventsPage = 1; loadEvents(); });
$('events-prev').addEventListener('click', () => { if (state.eventsPage > 1) { state.eventsPage--; loadEvents(); } });
$('events-next').addEventListener('click', () => { state.eventsPage++; loadEvents(); });
$('events-refresh').addEventListener('click', loadEvents);
$('events-export-json').addEventListener('click', () => exportData('events', 'json'));
$('events-export-csv').addEventListener('click', () => exportData('events', 'csv'));

function exportData(kind, format){
  const q = new URLSearchParams({kind, format});
  if (state.namespace !== 'all') q.set('namespace', state.namespace);
  if (kind === 'pods') { if (state.podsSearch) q.set('search', state.podsSearch); if (state.podsStatus) q.set('status', state.podsStatus); if (state.podsLabel) q.set('label_selector', state.podsLabel); }
  if (kind === 'deployments' && state.depsSearch) q.set('search', state.depsSearch);
  if (kind === 'events') { if (state.eventsType) q.set('type', state.eventsType); if (state.eventsSearch) q.set('search', state.eventsSearch); }
  window.location.href = '/api/export?' + q.toString();
}

/* event delegation for dynamically rendered buttons */
document.addEventListener('click', (e) => {
  const t = e.target.closest('[data-logs],[data-describe],[data-history],[data-try]');
  if (!t) return;
  if (t.dataset.logs) { showPage('logs'); setTimeout(() => { $('logs-pod').value = t.dataset.ns + '/' + t.dataset.logs; fetchLogs(); }, 300); }
  if (t.dataset.describe) { const [kind, name, ns] = t.dataset.describe.split(':'); showDescribe(kind, name, ns); }
  if (t.dataset.history) { const [ns, name] = t.dataset.history.split(':'); showHistory(ns, name); }
  if (t.dataset.try) tryTool(t.dataset.try, t.dataset.tool);
});
document.addEventListener('change', (e) => {
  const c = e.target.closest('.dep-check');
  if (!c) return;
  const key = c.dataset.ns + '/' + c.dataset.name;
  if (c.checked) state.selectedDeps.add(key); else state.selectedDeps.delete(key);
  updateBulkBar();
});

/* polling */
setInterval(() => {
  if (!$('autorefresh').checked || document.hidden) return;
  if (state.page === 'logs' && $('logs-follow').checked) fetchLogs();
  else refreshCurrent();
}, 5000);

/* boot */
renderTools();
loadStatus().then(() => { loadOverview(); });
</script>
</body>
</html>
"""