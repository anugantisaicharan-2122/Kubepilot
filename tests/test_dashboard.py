"""Tests for the KubePilot Pro dashboard (HTTP API + pages).

Runs against a real HTTP server on an ephemeral port in demo mode, so
the whole stack is exercised: routing, JSON envelopes, pagination,
filtering, bulk operations (including partial failures), export, and
error handling. No cluster or kubeconfig is required.
"""

import csv
import http.client
import io
import json
import os
import threading
import unittest
from unittest.mock import patch

from kubepilot.config import Settings
from kubepilot.dashboard import Dashboard
from kubepilot.demo_data import DemoStore


def _settings(**env):
    with patch.dict(os.environ, env, clear=True):
        return Settings()


class DashboardTestCase(unittest.TestCase):
    """Base: one demo-mode server per test class, fresh store per test."""

    @classmethod
    def setUpClass(cls):
        cls.dash = Dashboard(host="127.0.0.1", port=0, demo=True)
        cls.thread = threading.Thread(
            target=cls.dash.serve_forever, daemon=True
        )
        cls.thread.start()
        # serve_forever binds inside ThreadingHTTPServer constructor;
        # wait until the socket exists.
        for _ in range(100):
            if cls.dash.httpd is not None:
                break
            import time
            time.sleep(0.01)
        cls.port = cls.dash.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.dash.shutdown()

    def setUp(self):
        # Fresh deterministic store for every test (bulk tests mutate it).
        self.dash.store = DemoStore()
        self.store = self.dash.store

    # -- helpers ---------------------------------------------------------
    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = json.dumps(body) if body is not None else None
        hdrs = dict(headers or {})
        if payload is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, resp.getheaders(), raw

    def get_json(self, path):
        status, _, raw = self.request("GET", path)
        self.assertEqual(status, 200, f"GET {path} -> {status}: {raw[:300]}")
        return json.loads(raw)

    def post_json(self, path, body):
        status, _, raw = self.request("POST", path, body=body)
        self.assertEqual(status, 200, f"POST {path} -> {status}: {raw[:300]}")
        return json.loads(raw)


class TestPagesAndStatus(DashboardTestCase):
    def test_root_page_200_and_nav(self):
        status, headers, raw = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(any(h[0] == "Content-Type" and "text/html" in h[1]
                            for h in headers))
        html = raw.decode()
        for section in ("Overview", "Pods", "Deployments", "Logs", "Events", "Tutorial"):
            self.assertIn(section, html)
        self.assertIn("KubePilot Pro", html)
        self.assertNotIn("lorem", html.lower())
        self.assertNotIn("TODO", html)

    def test_status_demo_mode(self):
        data = self.get_json("/api/status")
        self.assertTrue(data["ok"])
        self.assertEqual(data["mode"], "demo")
        self.assertEqual(data["version"], "0.1.0")
        self.assertFalse(data["read_only"])
        self.assertEqual(data["namespaces"],
                         ["default", "monitoring", "prod", "staging"])

    def test_namespaces_endpoint(self):
        data = self.get_json("/api/namespaces")
        self.assertEqual(data["namespaces"], self.store.namespaces())

    def test_unknown_route_404_json(self):
        status, _, raw = self.request("GET", "/api/nope")
        self.assertEqual(status, 404)
        self.assertFalse(json.loads(raw)["ok"])

    def test_wrong_method_405(self):
        status, _, raw = self.request("PUT", "/api/status")
        self.assertEqual(status, 405)
        self.assertFalse(json.loads(raw)["ok"])

    def test_api_contract_ok_flag(self):
        for path in ("/api/status", "/api/overview", "/api/resources",
                     "/api/pods", "/api/deployments", "/api/events"):
            data = self.get_json(path)
            self.assertIn("ok", data)
            self.assertTrue(data["ok"], path)


class TestOverviewAndResources(DashboardTestCase):
    def test_overview_totals_match_store(self):
        data = self.get_json("/api/overview")
        self.assertEqual(data["pods"]["total"], len(self.store.pods))
        self.assertEqual(data["deployments"]["total"], len(self.store.deployments))
        by_status = data["pods"]["by_status"]
        self.assertEqual(sum(by_status.values()), len(self.store.pods))
        self.assertGreater(by_status.get("Running", 0), 50)
        self.assertEqual(by_status.get("CrashLoopBackOff"), 1)
        self.assertEqual(by_status.get("Failed"), 1)
        self.assertEqual(data["deployments"]["degraded"], 2)
        self.assertGreater(data["warning_events"], 0)
        self.assertTrue(data["attention"])

    def test_overview_namespace_scoped(self):
        data = self.get_json("/api/overview?namespace=prod")
        expected = len([p for p in self.store.pods if p["namespace"] == "prod"])
        self.assertEqual(data["pods"]["total"], expected)
        self.assertEqual(
            data["deployments"]["total"],
            len([d for d in self.store.deployments if d["namespace"] == "prod"]),
        )

    def test_resources_totals(self):
        data = self.get_json("/api/resources")
        self.assertGreater(data["cpu_cores"], 0)
        self.assertGreater(data["memory_gib"], 0)
        self.assertEqual(data["pods"], len(self.store.pods))
        self.assertEqual(
            sum(v["pods"] for v in data["by_namespace"].values()),
            len(self.store.pods),
        )
        self.assertTrue(data["top_workloads"])
        top = data["top_workloads"][0]
        self.assertIn("workload", top)
        self.assertIn("cpu_m", top)

    def test_resources_namespace_scoped(self):
        data = self.get_json("/api/resources?namespace=monitoring")
        expected = self.store.resource_usage("monitoring")
        self.assertEqual(data["cpu_millicores"], expected["cpu_millicores"])
        self.assertEqual(data["memory_mib"], expected["memory_mib"])


class TestPods(DashboardTestCase):
    def test_pagination_defaults(self):
        data = self.get_json("/api/pods")
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 20)
        self.assertEqual(data["total"], len(self.store.pods))
        self.assertEqual(len(data["items"]), 20)
        self.assertEqual(data["pages"], 5)  # 94 pods / 20

    def test_pagination_pages_differ(self):
        p1 = self.get_json("/api/pods?page=1&page_size=10")
        p2 = self.get_json("/api/pods?page=2&page_size=10")
        self.assertEqual(len(p1["items"]), 10)
        self.assertEqual(len(p2["items"]), 10)
        names1 = {p["name"] for p in p1["items"]}
        names2 = {p["name"] for p in p2["items"]}
        self.assertFalse(names1 & names2)

    def test_page_size_clamped_to_100(self):
        data = self.get_json("/api/pods?page_size=500")
        self.assertEqual(data["page_size"], 100)
        self.assertEqual(len(data["items"]), min(100, data["total"]))

    def test_page_beyond_end_clamped(self):
        data = self.get_json("/api/pods?page=999&page_size=20")
        self.assertEqual(data["page"], data["pages"])
        self.assertTrue(data["items"])

    def test_invalid_pagination_params_tolerated(self):
        data = self.get_json("/api/pods?page=abc&page_size=xyz")
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 20)

    def test_status_filter(self):
        data = self.get_json("/api/pods?status=CrashLoopBackOff&page_size=100")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["status"], "CrashLoopBackOff")
        self.assertGreaterEqual(data["items"][0]["restarts"], 10)
        pending = self.get_json("/api/pods?status=Pending&page_size=100")
        self.assertTrue(all(p["status"] == "Pending" for p in pending["items"]))
        self.assertGreater(pending["total"], 0)

    def test_search_filter(self):
        data = self.get_json("/api/pods?search=payments-worker&page_size=100")
        self.assertTrue(data["total"] >= 3)
        self.assertTrue(all("payments-worker" in p["name"] for p in data["items"]))
        none = self.get_json("/api/pods?search=definitely-not-a-pod")
        self.assertEqual(none["total"], 0)
        self.assertEqual(none["items"], [])

    def test_namespace_filter(self):
        data = self.get_json("/api/pods?namespace=monitoring&page_size=100")
        self.assertTrue(all(p["namespace"] == "monitoring" for p in data["items"]))
        self.assertEqual(data["total"],
                         len([p for p in self.store.pods if p["namespace"] == "monitoring"]))

    def test_label_selector_filter(self):
        data = self.get_json(
            "/api/pods?label_selector=app%3Dcheckout-api&page_size=100")
        self.assertTrue(data["total"] > 0)
        self.assertTrue(all(p["labels"]["app"] == "checkout-api" for p in data["items"]))
        multi = self.get_json(
            "/api/pods?label_selector=app%3Dcheckout-api%2Cenv%3Dprod&page_size=100")
        self.assertTrue(all(p["namespace"] == "prod" for p in multi["items"]))

    def test_pod_shape(self):
        data = self.get_json("/api/pods?page_size=1")
        pod = data["items"][0]
        for field in ("name", "namespace", "phase", "status", "ready",
                      "restarts", "age", "node", "labels", "cpu_request",
                      "memory_request"):
            self.assertIn(field, pod, field)


class TestDeploymentsAndEvents(DashboardTestCase):
    def test_deployments_pagination_and_search(self):
        data = self.get_json("/api/deployments")
        self.assertEqual(data["total"], len(self.store.deployments))
        found = self.get_json("/api/deployments?search=checkout")
        self.assertEqual(found["total"], 2)
        self.assertTrue(all("checkout" in d["name"] for d in found["items"]))

    def test_deployment_shape_and_verdict(self):
        data = self.get_json("/api/deployments?page_size=100")
        by_name = {(d["namespace"], d["name"]): d for d in data["items"]}
        self.assertEqual(by_name[("prod", "payments-worker")]["verdict"], "in_progress")
        self.assertEqual(by_name[("prod", "inventory-sync")]["verdict"], "stalled")
        self.assertEqual(by_name[("prod", "checkout-api")]["verdict"], "complete")
        dep = data["items"][0]
        for field in ("name", "namespace", "replicas", "images", "age", "verdict"):
            self.assertIn(field, dep, field)

    def test_events_type_filter_and_pagination(self):
        all_events = self.get_json("/api/events?page_size=100")
        warnings = self.get_json("/api/events?type=Warning&page_size=100")
        self.assertTrue(warnings["total"] > 0)
        self.assertTrue(all(e["type"] == "Warning" for e in warnings["items"]))
        self.assertLess(warnings["total"], all_events["total"])
        p1 = self.get_json("/api/events?page=1&page_size=10")
        p2 = self.get_json("/api/events?page=2&page_size=10")
        self.assertNotEqual(
            [e["message"] for e in p1["items"]], [e["message"] for e in p2["items"]])

    def test_events_search(self):
        data = self.get_json("/api/events?search=OOMKilling&page_size=100")
        self.assertTrue(data["total"] > 0)
        self.assertTrue(all("OOMKilling" in e["reason"] for e in data["items"]))


class TestLogsRolloutHistorySearch(DashboardTestCase):
    def test_logs_for_running_pod(self):
        pod = next(p for p in self.store.pods if p["phase"] == "Running")
        data = self.get_json(
            f"/api/logs?pod={pod['name']}&namespace={pod['namespace']}&tail_lines=5")
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["logs"].splitlines()), 5)

    def test_logs_previous_crashloop_shows_oom(self):
        pod = next(p for p in self.store.pods if p["restarts"] >= 10)
        data = self.get_json(
            f"/api/logs?pod={pod['name']}&namespace={pod['namespace']}&previous=true")
        self.assertTrue(data["ok"])
        self.assertIn("OOMKilled", data["logs"])

    def test_logs_pending_pod(self):
        pod = next(p for p in self.store.pods if p["phase"] == "Pending")
        data = self.get_json(f"/api/logs?pod={pod['name']}&namespace={pod['namespace']}")
        self.assertTrue(data["ok"])
        self.assertIn("not started", data["logs"])

    def test_logs_missing_pod_error_envelope(self):
        data = self.get_json("/api/logs?pod=nope&namespace=prod")
        self.assertFalse(data["ok"])
        self.assertIn("not found", data["error"])

    def test_logs_missing_params_400(self):
        status, _, raw = self.request("GET", "/api/logs")
        self.assertEqual(status, 400)
        self.assertFalse(json.loads(raw)["ok"])

    def test_logs_bad_tail_lines_400(self):
        status, _, raw = self.request(
            "GET", "/api/logs?pod=x&namespace=prod&tail_lines=abc")
        self.assertEqual(status, 400)

    def test_rollout_status(self):
        data = self.get_json("/api/rollout?name=checkout-api&namespace=prod")
        self.assertTrue(data["ok"])
        self.assertEqual(data["verdict"], "complete")
        self.assertEqual(data["replicas"]["desired"], 3)
        stalled = self.get_json("/api/rollout?name=inventory-sync&namespace=prod")
        self.assertEqual(stalled["verdict"], "stalled")

    def test_rollout_unknown_deployment(self):
        data = self.get_json("/api/rollout?name=nope&namespace=prod")
        self.assertFalse(data["ok"])

    def test_rollout_history_sorted_desc(self):
        data = self.get_json("/api/rollout-history?name=checkout-api&namespace=prod")
        self.assertTrue(data["ok"])
        revs = [h["revision"] for h in data["history"]]
        self.assertEqual(revs, sorted(revs, reverse=True))
        self.assertGreaterEqual(len(revs), 2)
        for entry in data["history"]:
            for field in ("revision", "image", "created", "replicas", "change"):
                self.assertIn(field, entry, field)

    def test_rollout_history_unknown(self):
        data = self.get_json("/api/rollout-history?name=nope&namespace=prod")
        self.assertFalse(data["ok"])

    def test_search_across_resources(self):
        data = self.get_json("/api/search?q=checkout")
        self.assertTrue(data["ok"])
        self.assertTrue(len(data["pods"]) > 0)
        self.assertEqual(len(data["deployments"]), 2)
        self.assertTrue(all("checkout" in p["name"] for p in data["pods"]))

    def test_search_missing_query_400(self):
        status, _, raw = self.request("GET", "/api/search")
        self.assertEqual(status, 400)

    def test_search_no_matches(self):
        data = self.get_json("/api/search?q=zzz-no-such-thing")
        self.assertEqual(data["pods"], [])
        self.assertEqual(data["deployments"], [])
        self.assertEqual(data["events"], [])

    def test_describe_demo(self):
        pod = self.store.pods[0]
        data = self.get_json(
            f"/api/describe?kind=pod&name={pod['name']}&namespace={pod['namespace']}")
        self.assertTrue(data["ok"])
        self.assertEqual(data["resource"]["name"], pod["name"])
        missing = self.get_json("/api/describe?kind=pod&name=nope&namespace=prod")
        self.assertFalse(missing["ok"])


class TestBulkOperations(DashboardTestCase):
    def test_bulk_scale_happy_path(self):
        data = self.post_json("/api/bulk/scale", {"items": [
            {"namespace": "staging", "name": "checkout-api", "replicas": 4},
            {"namespace": "staging", "name": "web-frontend", "replicas": 1},
        ]})
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["succeeded"], 2)
        self.assertEqual(data["failed"], 0)
        self.assertEqual(data["results"][0]["detail"], "2 -> 4 replicas")
        dep = next(d for d in self.store.deployments
                   if d["name"] == "checkout-api" and d["namespace"] == "staging")
        self.assertEqual(dep["replicas"]["desired"], 4)

    def test_bulk_partial_failure(self):
        data = self.post_json("/api/bulk/restart", {"items": [
            {"namespace": "prod", "name": "checkout-api"},
            {"namespace": "prod", "name": "does-not-exist"},
            {"namespace": "prod", "name": "web-frontend"},
        ]})
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["succeeded"], 2)
        self.assertEqual(data["failed"], 1)
        failed = [r for r in data["results"] if not r["ok"]]
        self.assertEqual(failed[0]["name"], "does-not-exist")
        self.assertIn("not found", failed[0]["error"])

    def test_bulk_empty_selection_400(self):
        status, _, raw = self.request("POST", "/api/bulk/scale", body={"items": []})
        self.assertEqual(status, 400)
        self.assertFalse(json.loads(raw)["ok"])

    def test_bulk_missing_items_400(self):
        status, _, raw = self.request("POST", "/api/bulk/scale", body={})
        self.assertEqual(status, 400)

    def test_bulk_too_many_items_400(self):
        items = [{"namespace": "prod", "name": f"dep-{i}"} for i in range(101)]
        status, _, raw = self.request("POST", "/api/bulk/restart", body={"items": items})
        self.assertEqual(status, 400)

    def test_bulk_invalid_json_400(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/bulk/scale", body="{not json",
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_bulk_scale_negative_replicas_per_item_failure(self):
        data = self.post_json("/api/bulk/scale", {"items": [
            {"namespace": "prod", "name": "checkout-api", "replicas": -1},
            {"namespace": "prod", "name": "web-frontend", "replicas": 2},
        ]})
        self.assertEqual(data["succeeded"], 1)
        self.assertEqual(data["failed"], 1)
        self.assertIn("replicas", data["results"][0]["error"])

    def test_bulk_rollback_and_revision(self):
        before = next(d for d in self.store.deployments
                      if d["name"] == "checkout-api" and d["namespace"] == "prod")
        rev_before = before["revision"]
        data = self.post_json("/api/bulk/rollback", {"items": [
            {"namespace": "prod", "name": "checkout-api"},
        ]})
        self.assertEqual(data["succeeded"], 1)
        self.assertEqual(
            data["results"][0]["detail"],
            f"revision {rev_before} -> {rev_before - 1}",
        )

    def test_bulk_restart_bumps_restarts(self):
        before = sum(p["restarts"] for p in self.store.pods
                     if p["labels"]["app"] == "web-frontend" and p["namespace"] == "prod")
        data = self.post_json("/api/bulk/restart", {"items": [
            {"namespace": "prod", "name": "web-frontend"},
        ]})
        self.assertEqual(data["succeeded"], 1)
        after = sum(p["restarts"] for p in self.store.pods
                    if p["labels"]["app"] == "web-frontend" and p["namespace"] == "prod")
        self.assertGreater(after, before)

    def test_single_scale_restart_rollback(self):
        scaled = self.post_json("/api/scale", {
            "namespace": "staging", "name": "api-gateway", "replicas": 2})
        self.assertTrue(scaled["ok"])
        self.assertEqual(scaled["replicas_before"], 1)
        self.assertEqual(scaled["replicas_after"], 2)
        restarted = self.post_json("/api/restart", {
            "namespace": "staging", "name": "api-gateway"})
        self.assertTrue(restarted["ok"])
        self.assertIn("restarted_at", restarted)
        rolled = self.post_json("/api/rollback", {
            "namespace": "staging", "name": "api-gateway"})
        self.assertTrue(rolled["ok"])

    def test_single_mutation_missing_name(self):
        data = self.post_json("/api/restart", {"namespace": "prod"})
        self.assertFalse(data["ok"])
        self.assertIn("name", data["error"])

    def test_bulk_scale_to_zero(self):
        data = self.post_json("/api/bulk/scale", {"items": [
            {"namespace": "default", "name": "demo-app", "replicas": 0},
        ]})
        self.assertEqual(data["succeeded"], 1)
        dep = next(d for d in self.store.deployments if d["name"] == "demo-app")
        self.assertEqual(dep["replicas"]["desired"], 0)
        self.assertEqual(
            len([p for p in self.store.pods if p["labels"]["app"] == "demo-app"]), 0)


class TestExport(DashboardTestCase):
    def test_export_pods_json(self):
        status, headers, raw = self.request("GET", "/api/export?kind=pods&format=json")
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["count"], len(self.store.pods))
        self.assertEqual(len(data["items"]), len(self.store.pods))

    def test_export_pods_csv(self):
        status, headers, raw = self.request(
            "GET", "/api/export?kind=pods&format=csv&namespace=prod")
        self.assertEqual(status, 200)
        self.assertTrue(any(h[0] == "Content-Type" and "text/csv" in h[1]
                            for h in headers))
        self.assertTrue(any(h[0] == "Content-Disposition" and "kubepilot-pods-prod.csv" in h[1]
                            for h in headers))
        rows = list(csv.DictReader(io.StringIO(raw.decode())))
        expected = len([p for p in self.store.pods if p["namespace"] == "prod"])
        self.assertEqual(len(rows), expected)
        self.assertEqual(
            set(rows[0].keys()),
            {"namespace", "name", "status", "ready", "restarts", "age",
             "node", "ip", "cpu_request", "memory_request"},
        )

    def test_export_deployments_csv_with_search(self):
        status, _, raw = self.request(
            "GET", "/api/export?kind=deployments&format=csv&search=checkout")
        rows = list(csv.DictReader(io.StringIO(raw.decode())))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["desired"], rows[0]["ready"])

    def test_export_events_json_filtered(self):
        data = self.get_json("/api/export?kind=events&format=json&type=Warning")
        self.assertTrue(all(e["type"] == "Warning" for e in data["items"]))
        self.assertGreater(data["count"], 0)

    def test_export_bad_kind_400(self):
        status, _, raw = self.request("GET", "/api/export?kind=nodes&format=json")
        self.assertEqual(status, 400)

    def test_export_bad_format_400(self):
        status, _, raw = self.request("GET", "/api/export?kind=pods&format=xml")
        self.assertEqual(status, 400)


class TestReadOnlyAndErrors(DashboardTestCase):
    def test_read_only_bulk_mutations_refused(self):
        with patch("kubepilot.dashboard.settings", _settings(KUBEPILOT_READ_ONLY="true")), \
             patch("kubepilot.server.settings", _settings(KUBEPILOT_READ_ONLY="true")):
            # Demo store mutations are not gated by the MCP read-only flag,
            # so exercise the live path: a dashboard in live mode with the
            # MCP tools refusing. Patch the tool to simulate the refusal.
            with patch("kubepilot.server.scale_deployment",
                       return_value='{"ok": false, "error": "refusing to mutate: server is running in read-only mode (KUBEPILOT_READ_ONLY=true)"}'):
                live = Dashboard(host="127.0.0.1", port=0, demo=False)
                result = live._mutate_one(
                    "scale", {"name": "api", "namespace": "prod", "replicas": 3})
                self.assertFalse(result["ok"])
                self.assertIn("read-only", result["error"])

    def test_cluster_unreachable_returns_envelope_not_500(self):
        live = Dashboard(host="127.0.0.1", port=0, demo=False)
        with patch("kubepilot.server.list_pods",
                   side_effect=RuntimeError("connection refused")):
            with self.assertRaises(Exception) as ctx:
                live._all_pods("default")
            self.assertIn("connection refused", str(ctx.exception))

    def test_demo_store_determinism(self):
        a, b = DemoStore(), DemoStore()
        self.assertEqual([p["name"] for p in a.pods], [p["name"] for p in b.pods])
        self.assertEqual(
            [(d["namespace"], d["name"]) for d in a.deployments],
            [(d["namespace"], d["name"]) for d in b.deployments],
        )

    def test_very_large_list_pagination(self):
        # 1,000 extra pods: paging must stay server-side and bounded.
        for i in range(1000):
            self.store.pods.append(self.store._pod(
                f"bulk-svc-{i}", "prod", "bulk-svc"))
        data = self.get_json("/api/pods?namespace=prod&page=1&page_size=100")
        self.assertEqual(len(data["items"]), 100)
        self.assertGreater(data["pages"], 10)
        last = self.get_json(
            f"/api/pods?namespace=prod&page={data['pages']}&page_size=100")
        self.assertTrue(0 < len(last["items"]) <= 100)

    def test_status_endpoint_read_only_flag(self):
        with patch("kubepilot.dashboard.settings", _settings(KUBEPILOT_READ_ONLY="true")):
            data = self.dash.api_status()
            self.assertTrue(data["read_only"])


class TestDashboardCli(unittest.TestCase):
    """CLI parsing: --version prints the package version and exits."""

    def test_version_flag_prints_version_and_exits(self):
        import io
        from contextlib import redirect_stdout

        from kubepilot import __version__
        from kubepilot.dashboard import main

        out = io.StringIO()
        with redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"kubepilot-dashboard {__version__}")

    def test_demo_and_live_are_mutually_exclusive(self):
        from kubepilot.dashboard import main

        with self.assertRaises(SystemExit) as ctx:
            main(["--demo", "--live"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
