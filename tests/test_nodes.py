"""Self-tests for graph/nodes.py — pure-ish, no grid contact.

Run from project root:
  .venv-graph/bin/python -m unittest tests.test_nodes -v
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "graph"))

import nodes as nd  # noqa: E402
from langgraph.graph import END  # noqa: E402


class TestRouteAfterPreflightLogs(unittest.TestCase):
    """Issue #6 Mode A: silent END after preflight must emit a classifier line."""

    def test_pass_returns_branch_no_log(self):
        # Happy path: no diagnostic line, just returns "mock" or "real".
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_preflight({"preflight": "pass", "mock": True})
        self.assertEqual(br, "mock")
        self.assertNotIn("terminating", buf.getvalue())

    def test_fail_init_logs_termination(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_preflight({
                "preflight": "fail_init",
                "config_name": "fooR00_03",
                "attempts": {"propose": 0},
            })
        self.assertEqual(br, END)
        out = buf.getvalue()
        self.assertIn("[graph] terminating fooR00_03", out)
        self.assertIn("preflight=fail_init", out)

    def test_retries_exhausted_logs(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_preflight({
                "preflight": "ambiguous",
                "config_name": "fooR00_07",
                "attempts": {"propose": nd.MAX_PROPOSE_RETRIES},
            })
        self.assertEqual(br, END)
        out = buf.getvalue()
        self.assertIn("fooR00_07", out)
        self.assertIn("ambiguous", out)
        self.assertIn(f"{nd.MAX_PROPOSE_RETRIES}/{nd.MAX_PROPOSE_RETRIES}", out)


class TestRouteAfterStageLogs(unittest.TestCase):
    """route_after_stage must say which stage triggered the END."""

    def test_no_failure_returns_next(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_stage({
                "stages": {"mubeam": {"status": "succeeded"}},
            })
        self.assertEqual(br, "next")
        self.assertNotIn("terminating", buf.getvalue())

    def test_failed_stage_logs(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_stage({
                "config_name": "fooR00_02",
                "stages": {
                    "mubeam": {"status": "succeeded"},
                    "mustops_ce": {"status": "failed"},
                },
            })
        self.assertEqual(br, END)
        out = buf.getvalue()
        self.assertIn("[graph] terminating fooR00_02", out)
        self.assertIn("mustops_ce", out)


class TestMakeStageNodeLogs(unittest.TestCase):
    """make_stage_node's silent except clause must emit a stage failure line."""

    def test_exception_prints_and_marks_failed(self):
        node = nd.make_stage_node("mubeam")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
             mock.patch.object(nd.pio, "run_stage",
                                side_effect=RuntimeError("boom")):
            out = node({"config_name": "fooR00_05", "stages": {}, "errors": []})
        self.assertEqual(out["stages"]["mubeam"]["status"], "failed")
        self.assertTrue(any("boom" in e for e in out["errors"]))
        log = buf.getvalue()
        self.assertIn("[graph] stage[mubeam/fooR00_05] FAILED", log)
        self.assertIn("boom", log)

    def test_no_exception_silent(self):
        node = nd.make_stage_node("mubeam")
        buf = io.StringIO()
        ok = {"cluster_id": "abc", "status": "succeeded", "n_done": 1,
              "n_failed": 0, "last_poll_ts": 0.0}
        with contextlib.redirect_stdout(buf), \
             mock.patch.object(nd.pio, "run_stage", return_value=ok):
            out = node({"config_name": "fooR00_05", "stages": {}, "errors": []})
        self.assertEqual(out["stages"]["mubeam"]["status"], "succeeded")
        self.assertNotIn("FAILED", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
