"""Unit tests for KubePilot.

No cluster, kubeconfig, or network access required: configuration is
tested in isolation and MCP tool registration is verified against the
in-memory server object.
"""

import asyncio
import os
import unittest
from unittest.mock import patch

from kubepilot.config import Settings, _as_bool, _as_int, _as_tuple


class TestHelpers(unittest.TestCase):
    def test_as_bool(self):
        self.assertTrue(_as_bool("true"))
        self.assertTrue(_as_bool("1"))
        self.assertTrue(_as_bool("YES"))
        self.assertTrue(_as_bool(" on "))
        self.assertFalse(_as_bool("false"))
        self.assertFalse(_as_bool("0"))
        self.assertFalse(_as_bool(None))
        self.assertTrue(_as_bool(None, default=True))

    def test_as_int(self):
        self.assertEqual(_as_int("50", 200), 50)
        self.assertEqual(_as_int(" 12 ", 200), 12)
        self.assertEqual(_as_int(None, 200), 200)
        # Malformed input falls back instead of raising.
        self.assertEqual(_as_int("abc", 200), 200)
        self.assertEqual(_as_int("", 200), 200)

    def test_as_tuple(self):
        self.assertEqual(_as_tuple("a,b , c"), ("a", "b", "c"))
        self.assertEqual(_as_tuple("single"), ("single",))
        self.assertEqual(_as_tuple(""), ())
        self.assertEqual(_as_tuple(None), ())


class TestSettings(unittest.TestCase):
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        self.assertEqual(s.default_namespace, "default")
        self.assertFalse(s.read_only)
        self.assertFalse(s.in_cluster)
        self.assertEqual(s.allowed_namespaces, ())
        self.assertEqual(s.max_log_lines, 200)
        # Empty allow-list means "no restriction".
        self.assertTrue(s.namespace_allowed("anything"))

    def test_env_overrides(self):
        env = {
            "KUBEPILOT_READ_ONLY": "true",
            "KUBEPILOT_IN_CLUSTER": "yes",
            "KUBEPILOT_ALLOWED_NAMESPACES": "default, staging",
            "KUBEPILOT_DEFAULT_NAMESPACE": "prod",
            "KUBEPILOT_MAX_LOG_LINES": "50",
            "KUBEPILOT_LOG_LEVEL": "debug",
        }
        with patch.dict(os.environ, env, clear=True):
            s = Settings()
        self.assertTrue(s.read_only)
        self.assertTrue(s.in_cluster)
        self.assertEqual(s.allowed_namespaces, ("default", "staging"))
        self.assertEqual(s.default_namespace, "prod")
        self.assertEqual(s.max_log_lines, 50)
        self.assertEqual(s.log_level, "DEBUG")
        self.assertTrue(s.namespace_allowed("staging"))
        self.assertFalse(s.namespace_allowed("kube-system"))

    def test_malformed_env_values_fall_back(self):
        # A bad KUBEPILOT_MAX_LOG_LINES must not crash Settings construction.
        with patch.dict(
            os.environ,
            {
                "KUBEPILOT_MAX_LOG_LINES": "not-a-number",
                "KUBEPILOT_DEFAULT_NAMESPACE": "   ",
            },
            clear=True,
        ):
            s = Settings()
        self.assertEqual(s.max_log_lines, 200)
        self.assertEqual(s.default_namespace, "default")

    def test_settings_are_immutable(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        with self.assertRaises(AttributeError):
            s.read_only = True  # type: ignore[misc]


class TestToolRegistration(unittest.TestCase):
    def test_all_tools_registered_with_descriptions(self):
        # Importing the server must not touch the cluster (lazy clients).
        from kubepilot.server import server

        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        expected = {
            "list_pods",
            "get_pod_logs",
            "list_deployments",
            "scale_deployment",
            "get_events",
            "describe_resource",
            "rollout_status",
            "restart_deployment",
            "rollback_deployment",
        }
        self.assertEqual(names, expected)
        for tool in tools:
            self.assertTrue(
                tool.description and len(tool.description) > 20,
                f"tool {tool.name!r} needs a useful description",
            )


if __name__ == "__main__":
    unittest.main()
