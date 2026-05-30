"""Self-tests for graph/closed_loop.py — pure-ish, no grid contact.

Run from project root:
  python -m unittest tests.test_closed_loop -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "graph"))

import closed_loop as cl  # noqa: E402


class TestRouteAfterDecide(unittest.TestCase):
    def _base(self, **overrides):
        s = {"zero_rows": False, "round_idx": 1, "max_rounds": 10}
        s.update(overrides)
        return s

    def test_zero_rows_ends(self):
        with mock.patch.object(cl, "_stop_requested", return_value=False):
            self.assertEqual(
                cl.route_after_decide(self._base(zero_rows=True)), cl.END
            )

    def test_max_rounds_ends(self):
        with mock.patch.object(cl, "_stop_requested", return_value=False):
            self.assertEqual(
                cl.route_after_decide(self._base(round_idx=10, max_rounds=10)),
                cl.END,
            )

    def test_stop_flag_ends(self):
        with mock.patch.object(cl, "_stop_requested", return_value=True):
            self.assertEqual(cl.route_after_decide(self._base()), cl.END)

    def test_default_loops_to_renew_token(self):
        with mock.patch.object(cl, "_stop_requested", return_value=False):
            self.assertEqual(cl.route_after_decide(self._base()), "renew_token")


class TestDecideNext(unittest.TestCase):
    def test_bumps_round_and_clears_children_only(self):
        state = {
            "mode": "helical",
            "round_idx": 2,
            "children": {"foo": {"pid": 1}},
            "completed_names": ["a", "b"],
            "history_len_before": 10,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=15):
            out = cl.node_decide_next(state)
        self.assertEqual(out["round_idx"], 3)
        self.assertEqual(out["children"], {})
        self.assertFalse(out["zero_rows"])
        # completed_names intentionally persists across rounds
        self.assertNotIn("completed_names", out)

    def test_zero_new_rows_sets_zero_rows_true(self):
        state = {
            "mode": "helical",
            "round_idx": 1,
            "children": {},
            "completed_names": [],
            "history_len_before": 42,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_decide_next(state)
        self.assertTrue(out["zero_rows"])
        self.assertEqual(out["round_idx"], 2)

    def test_negative_delta_sets_zero_rows_true(self):
        # Defensive: leaderboard shouldn't shrink, but if it does, treat
        # as zero-row (no progress) rather than continuing.
        state = {
            "mode": "helical",
            "round_idx": 1,
            "children": {},
            "completed_names": [],
            "history_len_before": 10,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=8):
            out = cl.node_decide_next(state)
        self.assertTrue(out["zero_rows"])


class TestAssignNames(unittest.TestCase):
    def _state(self):
        return {
            "name_prefix": "helical",
            "round_idx": 0,
            "mode": "helical",
            "children": {
                "_pick_00": {"x_point": [1, 2, 3, 4]},
                "_pick_01": {"x_point": [5, 6, 7, 8]},
            },
            "completed_names": [],
        }

    def test_placeholders_become_real_names(self):
        with mock.patch.object(cl, "_child_in_leaderboard", return_value=False), \
             mock.patch.object(cl, "_child_is_broken", return_value=False):
            out = cl.node_assign_names(self._state())
        self.assertEqual(
            sorted(out["children"]), ["helicalR00_00", "helicalR00_01"]
        )
        self.assertEqual(
            out["children"]["helicalR00_00"]["x_point"], [1, 2, 3, 4]
        )
        self.assertEqual(out["completed_names"], [])

    def test_already_in_leaderboard_skipped(self):
        in_lb = {"helicalR00_00"}
        with mock.patch.object(cl, "_child_in_leaderboard",
                                lambda n, m: n in in_lb), \
             mock.patch.object(cl, "_child_is_broken", return_value=False):
            out = cl.node_assign_names(self._state())
        self.assertNotIn("helicalR00_00", out["children"])
        self.assertIn("helicalR00_01", out["children"])
        self.assertIn("helicalR00_00", out["completed_names"])

    def test_broken_skipped(self):
        with mock.patch.object(cl, "_child_in_leaderboard", return_value=False), \
             mock.patch.object(cl, "_child_is_broken",
                                lambda n: n == "helicalR00_01"):
            out = cl.node_assign_names(self._state())
        self.assertIn("helicalR00_00", out["children"])
        self.assertNotIn("helicalR00_01", out["children"])
        self.assertIn("helicalR00_01", out["completed_names"])


class TestRenewToken(unittest.TestCase):
    @staticmethod
    def _ok():
        return mock.Mock(returncode=0, stderr="")

    @staticmethod
    def _fail():
        return mock.Mock(returncode=1, stderr="auth failed")

    def test_happy_path_no_errors(self):
        state = {"round_idx": 0, "errors": []}
        with mock.patch.object(cl.subprocess, "run",
                                side_effect=[self._ok(), self._ok()]):
            out = cl.node_renew_token(state)
        self.assertEqual(out["errors"], [])

    def test_getToken_nonzero_rc_exits(self):
        state = {"round_idx": 0, "errors": []}
        with mock.patch.object(cl.subprocess, "run",
                                side_effect=[self._ok(), self._fail()]):
            with self.assertRaises(SystemExit) as cm:
                cl.node_renew_token(state)
        self.assertEqual(cm.exception.code, 2)

    def test_getToken_raises_exits(self):
        state = {"round_idx": 0, "errors": []}

        def side(args, **kw):
            if args[0] == "kinit":
                return self._ok()
            raise OSError("ENOKEY")

        with mock.patch.object(cl.subprocess, "run", side_effect=side):
            with self.assertRaises(SystemExit) as cm:
                cl.node_renew_token(state)
        self.assertEqual(cm.exception.code, 2)

    def test_kinit_failure_does_not_exit(self):
        # kinit -R is best-effort; only getToken failure is fatal
        state = {"round_idx": 0, "errors": []}
        with mock.patch.object(cl.subprocess, "run",
                                side_effect=[self._fail(), self._ok()]):
            out = cl.node_renew_token(state)
        self.assertTrue(any("kinit -R" in e for e in out["errors"]))


class TestPredictPicks(unittest.TestCase):
    def test_under_q_logs_error(self):
        state = {"q": 5, "round_idx": 0, "errors": [], "mode": "helical"}
        fake_gp = mock.Mock()
        fake_gp.compute_explore_picks.return_value = [
            (1, 2, 3, 4), (5, 6, 7, 8),
        ]
        with mock.patch.object(cl, "_import_gp", return_value=fake_gp), \
             mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_predict_picks(state)
        self.assertTrue(any("only got 2/5 picks" in e for e in out["errors"]))
        self.assertEqual(len(out["children"]), 2)
        self.assertEqual(out["history_len_before"], 42)

    def test_full_q_no_error(self):
        state = {"q": 2, "round_idx": 0, "errors": [], "mode": "helical"}
        fake_gp = mock.Mock()
        fake_gp.compute_explore_picks.return_value = [
            (1, 2, 3, 4), (5, 6, 7, 8),
        ]
        with mock.patch.object(cl, "_import_gp", return_value=fake_gp), \
             mock.patch.object(cl, "_leaderboard_len", return_value=10):
            out = cl.node_predict_picks(state)
        self.assertEqual(out["errors"], [])
        self.assertEqual(sorted(out["children"]), ["_pick_00", "_pick_01"])
        self.assertEqual(out["history_len_before"], 10)


class TestChildIsBroken(unittest.TestCase):
    def test_broken_present(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp):
                state_dir = tmp / "fooR00_00" / "state"
                state_dir.mkdir(parents=True)
                (state_dir / "broken.txt").write_text("x")
                self.assertTrue(cl._child_is_broken("fooR00_00"))

    def test_broken_absent(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(cl, "GRID_DATA_ROOT", Path(td)):
                self.assertFalse(cl._child_is_broken("nope"))


class TestBuildGraph(unittest.TestCase):
    def test_renew_token_is_a_node(self):
        g = cl._build_outer_graph()
        # All expected nodes present; renew_token is the start-of-round node.
        for n in ("renew_token", "predict_picks", "assign_names",
                  "launch_children", "barrier", "decide_next"):
            self.assertIn(n, g.nodes, f"missing node {n}")

    def test_refit_and_check_removed(self):
        # Convergence-by-pareto-hash machinery was deleted 2026-05-29
        # (foilsX04 false-positive incident, 0 true saves in 15 runs).
        g = cl._build_outer_graph()
        self.assertNotIn("refit_and_check", g.nodes)


class TestUniqueThreadIdPerLaunch(unittest.TestCase):
    """Issue #7: closed_loop must pass a per-launch unique --thread-id so a
    stale SqliteSaver checkpoint keyed on `config_name` cannot resume into a
    fresh child and silently swap its identity.
    See wiki/incidents/closed-loop-thread-id-checkpoint-collision.md.
    """

    def _capture_cmd(self):
        """Stub Popen that records the cmd list and returns a fake proc."""
        captured = []

        class _FakeProc:
            def __init__(self, cmd):
                self.pid = 999
                self._cmd = cmd

        def _popen(cmd, **kwargs):
            captured.append(list(cmd))
            return _FakeProc(cmd)

        return captured, _popen

    def _state(self, td):
        # Two children sharing identical x_point shapes but different names.
        return {
            "mode": "helical",
            "alpha": 0.0,
            "stagger_sec": 0,
            "errors": [],
            "children": {
                "fooR00_00": {"x_point": [1.0, 2.0, 3.0, 4.0], "log": str(td / "a.log"), "pid": None, "started_at": 0.0},
                "fooR00_01": {"x_point": [5.0, 6.0, 7.0, 8.0], "log": str(td / "b.log"), "pid": None, "started_at": 0.0},
            },
        }

    def test_thread_id_unique_per_child(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            captured, popen = self._capture_cmd()
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch.object(cl.subprocess, "Popen", popen), \
                 mock.patch.object(cl, "_child_in_leaderboard", return_value=False):
                out = cl.node_launch_children(self._state(tmp))
            self.assertEqual(len(captured), 2)
            tids = [c[c.index("--thread-id") + 1] for c in captured]
            names = [c[c.index("--config-name") + 1] for c in captured]
            # config_name keeps the user-visible identity ...
            self.assertEqual(sorted(names), ["fooR00_00", "fooR00_01"])
            # ... but thread_id must NOT equal config_name (would collide).
            for tid, name in zip(tids, names):
                self.assertNotEqual(tid, name,
                                    f"thread_id {tid} == config_name {name}; collision-risk")
                self.assertTrue(tid.startswith(name + "_"),
                                f"thread_id {tid} should namespace under {name}")
            # And the two threads must differ from each other.
            self.assertNotEqual(tids[0], tids[1])
            # node persists thread_id on the child record (for barrier lookup).
            for name in names:
                self.assertIn("thread_id", out["children"][name])

    def test_thread_id_reused_on_resume(self):
        """A crashed parent re-entering launch_children with an already-set
        thread_id must reuse it — otherwise the barrier's checkpoint lookup
        (keyed on the FIRST-assigned thread_id) cannot find the child."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            captured, popen = self._capture_cmd()
            state = self._state(tmp)
            # Pre-populate one child with a thread_id (simulating prior launch).
            state["children"]["fooR00_00"]["thread_id"] = "fooR00_00_deadbeef"
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch.object(cl.subprocess, "Popen", popen), \
                 mock.patch.object(cl, "_child_in_leaderboard", return_value=False):
                cl.node_launch_children(state)
            for c in captured:
                if "fooR00_00" in c:
                    tid = c[c.index("--thread-id") + 1]
                    self.assertEqual(tid, "fooR00_00_deadbeef",
                                     "resume path must reuse the prior thread_id")


class TestTerminalCheckpointUsesThreadId(unittest.TestCase):
    """The barrier must look up checkpoints by the per-launch thread_id, not
    by the config_name — otherwise PR1's per-launch namespacing breaks the
    barrier's checkpoint fallback (preflight/stage-fail children would never
    resolve and the barrier would block until timeout)."""

    def test_passes_thread_id_to_get_state(self):
        seen = {}

        class _FakeGraph:
            def get_state(self, cfg):
                seen["cfg"] = cfg
                # Pretend nothing in the DB → not terminal.
                return None

        cl._child_terminal_via_checkpoint(
            "fooR00_00", _FakeGraph(), thread_id="fooR00_00_deadbeef"
        )
        self.assertEqual(seen["cfg"]["configurable"]["thread_id"], "fooR00_00_deadbeef")

    def test_falls_back_to_name_when_no_thread_id(self):
        """Legacy resume path: a children record from before the decoupling
        won't have `thread_id`; barrier must fall back to `name` so old
        in-flight rounds don't deadlock after upgrade."""
        seen = {}

        class _FakeGraph:
            def get_state(self, cfg):
                seen["cfg"] = cfg
                return None

        cl._child_terminal_via_checkpoint("fooR00_00", _FakeGraph(), thread_id=None)
        self.assertEqual(seen["cfg"]["configurable"]["thread_id"], "fooR00_00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
