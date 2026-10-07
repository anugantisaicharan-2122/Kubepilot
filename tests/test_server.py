"""Unit tests for KubePilot's server (tool) layer.

No cluster, kubeconfig, or network access required: the Kubernetes
client is replaced with mocks, and settings are swapped per-test with
environment-backed ``Settings`` instances.
"""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import kubepilot.server as server_mod
from kubepilot.config import Settings
from kubepilot.server import (
    _age,
    _api_error,
    _err,
    _event_time,
    _ok,
    _require_namespace,
    _summarize_deployment,
    _summarize_pod,
    describe_resource,
    get_events,
    get_pod_logs,
    list_deployments,
    list_pods,
    restart_deployment,
    rollback_deployment,
    rollout_status,
    scale_deployment,
)


def _settings(**env):
    """Build a Settings instance with the given env vars (and nothing else)."""
    with patch.dict(os.environ, env, clear=True):
        return Settings()


def _with_settings(**env):
    """Decorator: run the test with kubepilot.server.settings replaced."""
    return patch("kubepilot.server.settings", _settings(**env))


def _fake_pod(name="web-0", phase="Running", ready=True, restarts=2):
    created = datetime.now(timezone.utc) - timedelta(hours=3, minutes=12)
    status = SimpleNamespace(
        container_statuses=[
            SimpleNamespace(ready=ready, restart_count=restarts),
            SimpleNamespace(ready=True, restart_count=0),
        ],
        phase=phase,
        pod_ip="10.0.1.7",
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, creation_timestamp=created),
        status=status,
        spec=SimpleNamespace(node_name="node-1"),
    )


def _fake_deployment(name="web", replicas=3):
    created = datetime.now(timezone.utc) - timedelta(days=2, hours=5)
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, creation_timestamp=created),
        spec=SimpleNamespace(
            replicas=replicas,
            template=SimpleNamespace(
                spec=SimpleNamespace(
                    containers=[
                        SimpleNamespace(image="registry/web:1.2.3"),
                        SimpleNamespace(image="registry/web:1.2.3"),
                        SimpleNamespace(image="registry/sidecar:0.9"),
                    ]
                )
            ),
        ),
        status=SimpleNamespace(
            ready_replicas=replicas,
            updated_replicas=replicas,
            available_replicas=replicas,
        ),
    )


class TestEnvelopes(unittest.TestCase):
    def test_ok_envelope(self):
        payload = json.loads(_ok({"pods": ["a"]}))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["pods"], ["a"])

    def test_err_envelope(self):
        payload = json.loads(_err("boom"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "boom")


class TestAge(unittest.TestCase):
    def test_none_is_unknown(self):
        self.assertEqual(_age(None), "unknown")

    def test_seconds(self):
        ts = datetime.now(timezone.utc) - timedelta(seconds=45)
        self.assertEqual(_age(ts), "45s")

    def test_minutes(self):
        ts = datetime.now(timezone.utc) - timedelta(minutes=36)
        self.assertEqual(_age(ts), "36m")

    def test_hours(self):
        ts = datetime.now(timezone.utc) - timedelta(hours=2, minutes=15)
        self.assertEqual(_age(ts), "2h15m")

    def test_days(self):
        ts = datetime.now(timezone.utc) - timedelta(days=2, hours=4)
        self.assertEqual(_age(ts), "2d4h")


class TestSummaries(unittest.TestCase):
    def test_summarize_pod(self):
        summary = _summarize_pod(_fake_pod())
        self.assertEqual(summary["name"], "web-0")
        self.assertEqual(summary["phase"], "Running")
        self.assertEqual(summary["ready"], "2/2")
        self.assertEqual(summary["restarts"], 2)
        self.assertEqual(summary["age"], "3h12m")
        self.assertEqual(summary["ip"], "10.0.1.7")
        self.assertEqual(summary["node"], "node-1")

    def test_summarize_pod_without_container_statuses(self):
        pod = _fake_pod()
        pod.status.container_statuses = None
        summary = _summarize_pod(pod)
        self.assertEqual(summary["ready"], "0/0")
        self.assertEqual(summary["restarts"], 0)

    def test_summarize_deployment(self):
        summary = _summarize_deployment(_fake_deployment())
        self.assertEqual(summary["name"], "web")
        self.assertEqual(summary["replicas"]["desired"], 3)
        self.assertEqual(summary["replicas"]["ready"], 3)
        # Images are deduplicated and sorted.
        self.assertEqual(
            summary["images"], ["registry/sidecar:0.9", "registry/web:1.2.3"]
        )
        self.assertEqual(summary["age"], "2d5h")


class TestRequireNamespace(unittest.TestCase):
    @_with_settings(KUBEPILOT_ALLOWED_NAMESPACES="default, staging")
    def test_allowed_namespace_returns_none(self):
        self.assertIsNone(_require_namespace("staging"))

    @_with_settings(KUBEPILOT_ALLOWED_NAMESPACES="default, staging")
    def test_denied_namespace_returns_error_envelope(self):
        payload = json.loads(_require_namespace("kube-system"))
        self.assertFalse(payload["ok"])
        self.assertIn("kube-system", payload["error"])

    @_with_settings()
    def test_empty_allow_list_allows_everything(self):
        self.assertIsNone(_require_namespace("anything"))


class TestApiError(unittest.TestCase):
    def test_kubernetes_api_exception(self):
        from kubernetes.client import ApiException

        exc = ApiException(status=404, reason="Not Found")
        payload = json.loads(_api_error(exc))
        self.assertFalse(payload["ok"])
        self.assertIn("404", payload["error"])

    def test_unexpected_exception(self):
        payload = json.loads(_api_error(ValueError("bad value")))
        self.assertFalse(payload["ok"])
        self.assertIn("ValueError", payload["error"])
        self.assertIn("bad value", payload["error"])


class TestListPods(unittest.TestCase):
    @_with_settings()
    def test_lists_and_summarizes_pods(self):
        fake_api = MagicMock()
        fake_api.list_namespaced_pod.return_value.items = [
            _fake_pod("web-0"),
            _fake_pod("web-1", phase="Pending"),
        ]
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(list_pods(namespace="default"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["namespace"], "default")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["pods"][1]["phase"], "Pending")
        fake_api.list_namespaced_pod.assert_called_once_with(
            namespace="default", label_selector=None
        )

    @_with_settings()
    def test_passes_label_selector_through(self):
        fake_api = MagicMock()
        fake_api.list_namespaced_pod.return_value.items = []
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(
                list_pods(namespace="default", label_selector="app=web")
            )
        self.assertTrue(payload["ok"])
        fake_api.list_namespaced_pod.assert_called_once_with(
            namespace="default", label_selector="app=web"
        )

    @_with_settings(KUBEPILOT_ALLOWED_NAMESPACES="default")
    def test_denied_namespace_is_rejected(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(list_pods(namespace="kube-system"))
        self.assertFalse(payload["ok"])
        fake_api.list_namespaced_pod.assert_not_called()

    @_with_settings()
    def test_api_failure_becomes_error_envelope(self):
        from kubernetes.client import ApiException

        fake_api = MagicMock()
        fake_api.list_namespaced_pod.side_effect = ApiException(
            status=403, reason="Forbidden"
        )
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(list_pods(namespace="default"))
        self.assertFalse(payload["ok"])
        self.assertIn("403", payload["error"])


class TestGetPodLogs(unittest.TestCase):
    @_with_settings(KUBEPILOT_MAX_LOG_LINES="200")
    def test_tail_lines_are_clamped_to_max(self):
        fake_api = MagicMock()
        fake_api.read_namespaced_pod_log.return_value = "line1\nline2"
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(
                get_pod_logs("web-0", namespace="default", tail_lines=9999)
            )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tail_lines"], 200)
        _, kwargs = fake_api.read_namespaced_pod_log.call_args
        self.assertEqual(kwargs["tail_lines"], 200)
        self.assertIsNone(kwargs["container"])

    @_with_settings()
    def test_container_is_forwarded(self):
        fake_api = MagicMock()
        fake_api.read_namespaced_pod_log.return_value = ""
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(
                get_pod_logs(
                    "web-0", namespace="default", container="sidecar", tail_lines=10
                )
            )
        self.assertTrue(payload["ok"])
        _, kwargs = fake_api.read_namespaced_pod_log.call_args
        self.assertEqual(kwargs["container"], "sidecar")


class TestScaleDeployment(unittest.TestCase):
    @_with_settings(KUBEPILOT_READ_ONLY="true")
    def test_read_only_refuses_to_scale(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                scale_deployment("web", namespace="default", replicas=5)
            )
        self.assertFalse(payload["ok"])
        self.assertIn("read-only", payload["error"])
        fake_api.patch_namespaced_deployment_scale.assert_not_called()

    @_with_settings()
    def test_negative_replicas_rejected(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                scale_deployment("web", namespace="default", replicas=-1)
            )
        self.assertFalse(payload["ok"])
        self.assertIn("0 or greater", payload["error"])
        fake_api.patch_namespaced_deployment_scale.assert_not_called()

    @_with_settings()
    def test_successful_scale_reports_before_and_after(self):
        fake_api = MagicMock()
        fake_api.read_namespaced_deployment_scale.return_value.spec.replicas = 3
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                scale_deployment("web", namespace="default", replicas=5)
            )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["replicas_before"], 3)
        self.assertEqual(payload["replicas_after"], 5)
        fake_api.patch_namespaced_deployment_scale.assert_called_once_with(
            "web", "default", {"spec": {"replicas": 5}}
        )


class TestListDeployments(unittest.TestCase):
    @_with_settings()
    def test_lists_and_summarizes_deployments(self):
        fake_api = MagicMock()
        fake_api.list_namespaced_deployment.return_value.items = [
            _fake_deployment("web"),
            _fake_deployment("api", replicas=1),
        ]
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(list_deployments(namespace="default"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["namespace"], "default")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["deployments"][1]["name"], "api")
        self.assertEqual(payload["deployments"][1]["replicas"]["desired"], 1)
        fake_api.list_namespaced_deployment.assert_called_once_with(
            namespace="default"
        )

    @_with_settings(KUBEPILOT_ALLOWED_NAMESPACES="default")
    def test_denied_namespace_is_rejected(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(list_deployments(namespace="kube-system"))
        self.assertFalse(payload["ok"])
        fake_api.list_namespaced_deployment.assert_not_called()

    @_with_settings()
    def test_api_failure_becomes_error_envelope(self):
        from kubernetes.client import ApiException

        fake_api = MagicMock()
        fake_api.list_namespaced_deployment.side_effect = ApiException(
            status=503, reason="Unavailable"
        )
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(list_deployments(namespace="default"))
        self.assertFalse(payload["ok"])
        self.assertIn("503", payload["error"])


def _fake_event(name, minutes_ago, message="pulled image", count=1,
                use_last_ts=True):
    """Build a minimal fake Kubernetes event."""
    created = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return SimpleNamespace(
        last_timestamp=created if use_last_ts else None,
        event_time=None,
        type="Normal",
        reason="Pulled",
        involved_object=SimpleNamespace(kind="Pod", name=name),
        message=message,
        count=count,
        metadata=SimpleNamespace(creation_timestamp=created),
    )


class TestEventTime(unittest.TestCase):
    def test_prefers_last_timestamp(self):
        event = _fake_event("web-0", 5)
        self.assertEqual(_event_time(event), event.last_timestamp)

    def test_falls_back_to_event_time(self):
        event = _fake_event("web-0", 5, use_last_ts=False)
        event.event_time = datetime.now(timezone.utc) - timedelta(minutes=3)
        self.assertEqual(_event_time(event), event.event_time)

    def test_falls_back_to_creation_timestamp(self):
        event = _fake_event("web-0", 5, use_last_ts=False)
        self.assertEqual(
            _event_time(event), event.metadata.creation_timestamp
        )


class TestGetEvents(unittest.TestCase):
    @_with_settings()
    def test_returns_events_newest_first(self):
        fake_api = MagicMock()
        fake_api.list_namespaced_event.return_value.items = [
            _fake_event("old", minutes_ago=60),
            _fake_event("new", minutes_ago=2),
        ]
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(get_events(namespace="default"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["namespace"], "default")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            [e["object"] for e in payload["events"]],
            ["Pod/new", "Pod/old"],
        )
        first = payload["events"][0]
        self.assertEqual(first["type"], "Normal")
        self.assertEqual(first["reason"], "Pulled")
        self.assertEqual(first["count"], 1)
        self.assertEqual(first["message"], "pulled image")
        self.assertTrue(first["last_seen"])

    @_with_settings()
    def test_limit_is_honored(self):
        fake_api = MagicMock()
        fake_api.list_namespaced_event.return_value.items = [
            _fake_event(f"pod-{i}", minutes_ago=i) for i in range(3)
        ]
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(get_events(namespace="default", limit=2))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["events"]), 2)

    @_with_settings()
    def test_long_messages_are_truncated(self):
        fake_api = MagicMock()
        fake_api.list_namespaced_event.return_value.items = [
            _fake_event("web-0", 1, message="m" * 400)
        ]
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(get_events(namespace="default"))
        self.assertEqual(len(payload["events"][0]["message"]), 300)

    @_with_settings(KUBEPILOT_ALLOWED_NAMESPACES="default")
    def test_denied_namespace_is_rejected(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(get_events(namespace="kube-system"))
        self.assertFalse(payload["ok"])
        fake_api.list_namespaced_event.assert_not_called()

    @_with_settings()
    def test_api_failure_becomes_error_envelope(self):
        from kubernetes.client import ApiException

        fake_api = MagicMock()
        fake_api.list_namespaced_event.side_effect = ApiException(
            status=403, reason="Forbidden"
        )
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(get_events(namespace="default"))
        self.assertFalse(payload["ok"])
        self.assertIn("403", payload["error"])


class TestDescribeResource(unittest.TestCase):
    @_with_settings()
    def test_unsupported_kind_rejected(self):
        payload = json.loads(describe_resource("cronjob", "nightly"))
        self.assertFalse(payload["ok"])
        self.assertIn("unsupported kind", payload["error"])

    @_with_settings(KUBEPILOT_ALLOWED_NAMESPACES="default")
    def test_namespaced_kind_honors_allow_list(self):
        payload = json.loads(
            describe_resource("pod", "web-0", namespace="kube-system")
        )
        self.assertFalse(payload["ok"])
        self.assertIn("kube-system", payload["error"])

    @_with_settings()
    def test_strips_managed_fields(self):
        fake_api = MagicMock()
        fake_api.read_node.return_value.to_dict.return_value = {
            "metadata": {
                "name": "node-1",
                "managed_fields": [{"manager": "kubelet"}],
            },
            "status": {"phase": "Ready"},
        }
        with patch.object(server_mod.k8s, "core_v1", return_value=fake_api):
            payload = json.loads(describe_resource("node", "node-1"))
        self.assertTrue(payload["ok"])
        self.assertNotIn("managed_fields", payload["resource"]["metadata"])
        self.assertEqual(payload["resource"]["status"]["phase"], "Ready")


def _fake_deployment_with_revision(
    name="web", replicas=3, revision=3, conditions=None, unavailable=0
):
    """Fake deployment carrying a revision annotation and conditions."""
    dep = _fake_deployment(name, replicas)
    dep.metadata.annotations = {
        "deployment.kubernetes.io/revision": str(revision)
    }
    dep.metadata.uid = "dep-uid-123"
    dep.status.conditions = conditions or []
    dep.status.unavailable_replicas = unavailable
    return dep


def _fake_replicaset(name, revision, owner_uid="dep-uid-123", controller=True):
    """Fake ReplicaSet owned by the fake deployment, template as plain dict."""
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            uid=f"rs-{name}",
            annotations={
                "deployment.kubernetes.io/revision": str(revision)
            },
            owner_references=[
                SimpleNamespace(uid=owner_uid, controller=controller)
            ],
        ),
        spec=SimpleNamespace(
            template={
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "containers": [
                        {"name": "web", "image": f"registry/web:1.0.{revision}"}
                    ]
                },
            }
        ),
    )


def _progress_condition(reason="NewReplicaSetAvailable"):
    return SimpleNamespace(
        type="Progressing",
        status="True",
        reason=reason,
        message="ReplicaSet updated",
    )


class TestRolloutStatus(unittest.TestCase):
    @_with_settings()
    def test_complete_rollout(self):
        dep = _fake_deployment_with_revision(
            revision=4, conditions=[_progress_condition()]
        )
        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.return_value = dep
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(rollout_status("web", namespace="default"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["verdict"], "complete")
        self.assertEqual(payload["revision"], 4)
        self.assertEqual(payload["replicas"]["desired"], 3)
        self.assertEqual(payload["replicas"]["available"], 3)
        self.assertEqual(len(payload["conditions"]), 1)

    @_with_settings()
    def test_in_progress_rollout(self):
        dep = _fake_deployment_with_revision(revision=5)
        dep.status.updated_replicas = 1
        dep.status.ready_replicas = 1
        dep.status.available_replicas = 1
        dep.status.unavailable_replicas = 2
        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.return_value = dep
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(rollout_status("web", namespace="default"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["verdict"], "in_progress")
        self.assertEqual(payload["replicas"]["unavailable"], 2)

    @_with_settings()
    def test_stalled_rollout(self):
        dep = _fake_deployment_with_revision(
            revision=5,
            conditions=[_progress_condition("ProgressDeadlineExceeded")],
        )
        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.return_value = dep
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(rollout_status("web", namespace="default"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["verdict"], "stalled")

    @_with_settings(KUBEPILOT_READ_ONLY="true")
    def test_read_only_does_not_block_status(self):
        dep = _fake_deployment_with_revision()
        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.return_value = dep
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(rollout_status("web", namespace="default"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["verdict"], "complete")

    @_with_settings(KUBEPILOT_ALLOWED_NAMESPACES="default")
    def test_denied_namespace_is_rejected(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(rollout_status("web", namespace="kube-system"))
        self.assertFalse(payload["ok"])
        fake_api.read_namespaced_deployment.assert_not_called()

    @_with_settings()
    def test_api_failure_becomes_error_envelope(self):
        from kubernetes.client import ApiException

        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.side_effect = ApiException(
            status=404, reason="Not Found"
        )
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(rollout_status("web", namespace="default"))
        self.assertFalse(payload["ok"])
        self.assertIn("404", payload["error"])


class TestRestartDeployment(unittest.TestCase):
    @_with_settings(KUBEPILOT_READ_ONLY="true")
    def test_read_only_refuses_to_restart(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                restart_deployment("web", namespace="default")
            )
        self.assertFalse(payload["ok"])
        self.assertIn("read-only", payload["error"])
        fake_api.patch_namespaced_deployment.assert_not_called()

    @_with_settings(KUBEPILOT_ALLOWED_NAMESPACES="default")
    def test_denied_namespace_is_rejected(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                restart_deployment("web", namespace="kube-system")
            )
        self.assertFalse(payload["ok"])
        fake_api.patch_namespaced_deployment.assert_not_called()

    @_with_settings()
    def test_successful_restart_patches_annotation(self):
        dep = _fake_deployment_with_revision(revision=4)
        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.return_value = dep
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                restart_deployment("web", namespace="default")
            )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deployment"], "web")
        self.assertTrue(payload["restarted_at"])
        _, kwargs_or_args = fake_api.patch_namespaced_deployment.call_args
        body = fake_api.patch_namespaced_deployment.call_args[0][2]
        restarted = body["spec"]["template"]["metadata"]["annotations"][
            "kubectl.kubernetes.io/restartedAt"
        ]
        self.assertTrue(restarted)

    @_with_settings()
    def test_api_failure_becomes_error_envelope(self):
        from kubernetes.client import ApiException

        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.return_value = (
            _fake_deployment_with_revision()
        )
        fake_api.patch_namespaced_deployment.side_effect = ApiException(
            status=403, reason="Forbidden"
        )
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                restart_deployment("web", namespace="default")
            )
        self.assertFalse(payload["ok"])
        self.assertIn("403", payload["error"])


class TestRollbackDeployment(unittest.TestCase):
    @_with_settings(KUBEPILOT_READ_ONLY="true")
    def test_read_only_refuses_to_roll_back(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                rollback_deployment("web", namespace="default")
            )
        self.assertFalse(payload["ok"])
        self.assertIn("read-only", payload["error"])
        fake_api.patch_namespaced_deployment.assert_not_called()

    @_with_settings(KUBEPILOT_ALLOWED_NAMESPACES="default")
    def test_denied_namespace_is_rejected(self):
        fake_api = MagicMock()
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                rollback_deployment("web", namespace="kube-system")
            )
        self.assertFalse(payload["ok"])
        fake_api.patch_namespaced_deployment.assert_not_called()

    @_with_settings()
    def test_no_previous_revision_is_an_error(self):
        dep = _fake_deployment_with_revision(revision=1)
        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.return_value = dep
        fake_api.list_namespaced_replica_set.return_value.items = [
            _fake_replicaset("web-abc", 1)
        ]
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                rollback_deployment("web", namespace="default")
            )
        self.assertFalse(payload["ok"])
        self.assertIn("no earlier revision", payload["error"])
        fake_api.patch_namespaced_deployment.assert_not_called()

    @_with_settings()
    def test_rolls_back_to_newest_older_revision(self):
        dep = _fake_deployment_with_revision(revision=3)
        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.return_value = dep
        fake_api.list_namespaced_replica_set.return_value.items = [
            _fake_replicaset("web-old", 1),
            _fake_replicaset("web-prev", 2),
            _fake_replicaset("web-current", 3),
            # Belongs to another deployment: must be ignored.
            _fake_replicaset("other-xyz", 2, owner_uid="other-dep"),
        ]
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                rollback_deployment("web", namespace="default")
            )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["revision_before"], 3)
        self.assertEqual(payload["revision_after"], 2)
        body = fake_api.patch_namespaced_deployment.call_args[0][2]
        template = body["spec"]["template"]
        image = template["spec"]["containers"][0]["image"]
        self.assertEqual(image, "registry/web:1.0.2")

    @_with_settings()
    def test_api_failure_becomes_error_envelope(self):
        from kubernetes.client import ApiException

        fake_api = MagicMock()
        fake_api.read_namespaced_deployment.side_effect = ApiException(
            status=404, reason="Not Found"
        )
        with patch.object(server_mod.k8s, "apps_v1", return_value=fake_api):
            payload = json.loads(
                rollback_deployment("web", namespace="default")
            )
        self.assertFalse(payload["ok"])
        self.assertIn("404", payload["error"])


if __name__ == "__main__":
    unittest.main()
