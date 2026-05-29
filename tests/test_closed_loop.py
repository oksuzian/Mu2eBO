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


class TestParetoHash(unittest.TestCase):
    def test_identical_picks_same_hash(self):
        a = [(1.234, 5.678), (9.0, 0.1)]
        self.assertEqual(cl._pareto_hash(a), cl._pareto_hash(list(a)))

    def test_jitter_within_2sigfig_same_hash(self):
        # 1.234 and 1.236 both round to 1.2; 5.678 and 5.671 both round to 5.7
        self.assertEqual(
            cl._pareto_hash([(1.234, 5.678)]),
            cl._pareto_hash([(1.236, 5.671)]),
        )

    def test_reorder_same_hash(self):
        a = [(1.0, 2.0), (3.0, 4.0)]
        b = [(3.0, 4.0), (1.0, 2.0)]
        self.assertEqual(cl._pareto_hash(a), cl._pareto_hash(b))

    def test_different_picks_different_hash(self):
        self.assertNotEqual(
            cl._pareto_hash([(1.0, 2.0)]),
            cl._pareto_hash([(10.0, 20.0)]),
        )

    def test_empty_stable(self):
        self.assertEqual(cl._pareto_hash([]), cl._pareto_hash([]))


class TestRouteAfterDecide(unittest.TestCase):
    def _base(self, **overrides):
        s = {"converged": False, "round_idx": 1, "max_rounds": 10}
        s.update(overrides)
        return s

    def test_converged_ends(self):
        with mock.patch.object(cl, "_stop_requested", return_value=False):
            self.assertEqual(
                cl.route_after_decide(self._base(converged=True)), cl.END
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
            "round_idx": 2,
            "children": {"foo": {"pid": 1}},
            "completed_names": ["a", "b"],
            "pareto_hashes": ["h1"],
        }
        out = cl.node_decide_next(state)
        self.assertEqual(out["round_idx"], 3)
        self.assertEqual(out["children"], {})
        # completed_names + pareto_hashes intentionally persist across rounds
        self.assertNotIn("completed_names", out)
        self.assertNotIn("pareto_hashes", out)


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
        with mock.patch.object(cl, "_import_gp", return_value=fake_gp):
            out = cl.node_predict_picks(state)
        self.assertTrue(any("only got 2/5 picks" in e for e in out["errors"]))
        self.assertEqual(len(out["children"]), 2)

    def test_full_q_no_error(self):
        state = {"q": 2, "round_idx": 0, "errors": [], "mode": "helical"}
        fake_gp = mock.Mock()
        fake_gp.compute_explore_picks.return_value = [
            (1, 2, 3, 4), (5, 6, 7, 8),
        ]
        with mock.patch.object(cl, "_import_gp", return_value=fake_gp):
            out = cl.node_predict_picks(state)
        self.assertEqual(out["errors"], [])
        self.assertEqual(sorted(out["children"]), ["_pick_00", "_pick_01"])


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
                  "launch_children", "barrier", "refit_and_check",
                  "decide_next"):
            self.assertIn(n, g.nodes, f"missing node {n}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
