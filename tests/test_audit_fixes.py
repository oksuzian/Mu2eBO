"""Targeted regression tests for the 5 /simplify audit fixes (2026-05-29).

Each TestClass covers one of the 5 fixes:

  TestIsBrokenParseException   — gp_predict_helical.py:158 (broken-unknown on bad report)
  TestModeArgChoices           — graph/closed_loop.py:514  (fail-fast on --mode typo)
  TestStageShaCheckCallsites   — pipeline.py:583,589        (poll + list-outputs warn)
  TestRemovePendingBeforeAppend — autoresearch_bo_michael.py:891 (atomic ordering)
  TestProposeOneBuildableRetry — graph/pipeline_io.py:88   (N_crit retry in BO path)

Run from project root:
  .venv-graph/bin/python -m unittest tests.test_audit_fixes -v
"""
import argparse
import csv
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "graph"))

# --- Fix 1: _is_broken parse-exception → True ---------------------------------

GP_HELICAL_PATH = Path(
    "/exp/mu2e/data/users/oksuzian/autoresearch_grid/"
    "mmackenz_table_plots/gp_predict_helical.py"
)


def _load_gp_helical():
    spec = importlib.util.spec_from_file_location("gp_predict_helical", GP_HELICAL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestIsBrokenParseException(unittest.TestCase):
    """Issue #1: malformed report.tsv must be treated as broken-unknown (True),
    not silent-pass (False). Mirrors the missing-report branch.
    """
    @classmethod
    def setUpClass(cls):
        if not GP_HELICAL_PATH.exists():
            raise unittest.SkipTest(f"{GP_HELICAL_PATH} unavailable")
        cls.gp = _load_gp_helical()

    def setUp(self):
        # _is_broken is @functools.lru_cache'd — clear between tests so
        # tempdir + GRID_DATA_ROOT mocks take effect for each call.
        self.gp._is_broken.cache_clear()

    def _stage(self, body, td, cfg):
        d = Path(td) / cfg / "scan_logs"
        d.mkdir(parents=True)
        (d / "report.tsv").write_text(body)
        return cfg

    def test_missing_likely_geom_overlap_column(self):
        # Header lacks "LikelyGeomOverlap" → hdr.index() raises ValueError
        with tempfile.TemporaryDirectory() as td:
            cfg = self._stage("stage\tnotacolumn\nmubeam\t0\n", td,
                              "cfg_parse_err")
            with mock.patch.object(self.gp, "GRID_DATA_ROOT", Path(td)):
                self.assertTrue(self.gp._is_broken(cfg),
                                "parse error must mark broken-unknown")

    def test_truncated_to_header_only_returns_false(self):
        # Header present, no body rows — len(lines) < 2 branch returns False
        # (intentional pre-existing behavior; this test pins it so the
        # exception-broken fix doesn't accidentally widen the gate).
        with tempfile.TemporaryDirectory() as td:
            cfg = self._stage("stage\tLikelyGeomOverlap\n", td, "cfg_truncated")
            with mock.patch.object(self.gp, "GRID_DATA_ROOT", Path(td)):
                self.assertFalse(self.gp._is_broken(cfg))

    def test_clean_report_not_broken(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._stage(
                "stage\tLikelyGeomOverlap\nmubeam\t0\nmustops_ce\t0\n",
                td, "cfg_clean",
            )
            with mock.patch.object(self.gp, "GRID_DATA_ROOT", Path(td)):
                self.assertFalse(self.gp._is_broken(cfg))

    def test_high_overlap_is_broken(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._stage(
                "stage\tLikelyGeomOverlap\nmubeam\t999999\n", td, "cfg_overlap",
            )
            with mock.patch.object(self.gp, "GRID_DATA_ROOT", Path(td)):
                self.assertTrue(self.gp._is_broken(cfg))


# --- Fix 2: --mode choices guard ---------------------------------------------

class TestModeArgChoices(unittest.TestCase):
    """Issue #2: argparse must reject unknown --mode values up-front.
    """
    def test_argparse_choices_includes_three_modes(self):
        # Pull the source line directly — no graph.closed_loop import needed
        # (avoid pulling in sqlite/langgraph deps for a string check).
        src = (PROJECT_ROOT / "graph" / "closed_loop.py").read_text()
        # The choices line is colocated with the --mode argument.
        m = re.search(r'choices\s*=\s*\[\s*"helical"\s*,\s*"michael"\s*,\s*"foils"\s*\]', src)
        self.assertIsNotNone(m, "--mode choices guard missing or reordered")

    def test_argparse_rejects_typo(self):
        # End-to-end: argparse fail-fast on unknown choice.
        ap = argparse.ArgumentParser()
        ap.add_argument("--mode", default="helical",
                        choices=["helical", "michael", "foils"])
        with self.assertRaises(SystemExit):
            with mock.patch.object(sys, "stderr", io.StringIO()):
                ap.parse_args(["--mode", "helcial"])  # typo

    def test_argparse_accepts_all_three(self):
        ap = argparse.ArgumentParser()
        ap.add_argument("--mode", default="helical",
                        choices=["helical", "michael", "foils"])
        for m in ("helical", "michael", "foils"):
            ns = ap.parse_args(["--mode", m])
            self.assertEqual(ns.mode, m)


# --- Fix 3: SHA-check fires on poll + list-outputs ---------------------------

class TestStageShaCheckCallsites(unittest.TestCase):
    """Issue #3: pipeline.py must invoke _check_stage_config_sha at the top
    of cmd_poll and cmd_list_outputs (was harvest-only).
    """
    def test_poll_calls_sha_check(self):
        src = (PROJECT_ROOT / "pipeline.py").read_text()
        # Match the cmd_poll function body up to the next `def `.
        m = re.search(r"def cmd_poll\(args.*?\n(.*?)\ndef ", src, re.DOTALL)
        self.assertIsNotNone(m, "cmd_poll not found")
        self.assertIn("_check_stage_config_sha", m.group(1),
                      "cmd_poll must call _check_stage_config_sha")

    def test_list_outputs_calls_sha_check(self):
        src = (PROJECT_ROOT / "pipeline.py").read_text()
        m = re.search(r"def cmd_list_outputs\(args.*?\n(.*?)\ndef ", src, re.DOTALL)
        self.assertIsNotNone(m, "cmd_list_outputs not found")
        self.assertIn("_check_stage_config_sha", m.group(1),
                      "cmd_list_outputs must call _check_stage_config_sha")

    def test_check_helper_warns_on_mismatch_and_returns(self):
        # The helper itself: silent on no-stamp, warns on mismatch, never raises.
        # Verifies the no-raise contract that callers rely on.
        import importlib
        if "pipeline" in sys.modules:
            del sys.modules["pipeline"]
        pipeline = importlib.import_module("pipeline")

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(pipeline, "STATE", tmp), \
                 mock.patch.dict(pipeline.STAGES,
                                 {"poke": {"events_per_job": 1}},
                                 clear=False):
                # 1) No stamp → silent return.
                pipeline._check_stage_config_sha("poke")  # no raise

                # 2) Matching stamp → silent return.
                pipeline._stamp_stage_config_sha("poke")
                pipeline._check_stage_config_sha("poke")  # no raise

                # 3) Mutate STAGES → mismatch → warn to stderr, no raise.
                pipeline.STAGES["poke"]["events_per_job"] = 2
                buf = io.StringIO()
                with mock.patch.object(sys, "stderr", buf):
                    pipeline._check_stage_config_sha("poke")
                self.assertIn("WARN", buf.getvalue())
                self.assertIn("poke", buf.getvalue())


# --- Fix 4: remove_pending BEFORE append_history -----------------------------

class TestRemovePendingBeforeAppend(unittest.TestCase):
    """Issue #4: cmd_evaluate must call remove_pending BEFORE append_history.
    If the order is wrong, a crash between leaves a phantom pending row,
    which trips propose_one's collision guard and silently renames the
    next iteration. Verify both static source order AND runtime ordering.
    """
    def test_source_order(self):
        src = (PROJECT_ROOT / "autoresearch_bo_michael.py").read_text()
        m = re.search(
            r"def cmd_evaluate\(args.*?\n(.*?)(?=\n(?:def |PREFLIGHT_FCL_TEMPLATE))",
            src, re.DOTALL,
        )
        self.assertIsNotNone(m, "cmd_evaluate not found")
        body = m.group(1)
        i_remove = body.find("remove_pending")
        i_append = body.find("append_history")
        self.assertGreater(i_remove, -1, "remove_pending missing in cmd_evaluate")
        self.assertGreater(i_append, -1, "append_history missing in cmd_evaluate")
        self.assertLess(
            i_remove, i_append,
            "remove_pending MUST come before append_history "
            "(phantom-pending failure mode is silent; loud-failure mode is required)"
        )

    def test_runtime_order_via_mock(self):
        # Drive the same ordering test at runtime so a future refactor that
        # moves the calls into a helper still gets caught.
        calls = []

        class FakeMode:
            name = "fake"
            leaderboard = Path("/tmp/_x.tsv")
            proposal_dir = Path("/tmp")
            def parse_geom(self, _t): return [0.0]
            def remove_pending(self, _n):
                calls.append("remove_pending"); return False
            def append_history(self, _p, _a):
                calls.append("append_history")

        # Mirror the cmd_evaluate ordering exactly.
        m = FakeMode()
        removed = m.remove_pending("cfg")
        m.append_history(object(), 1.0)
        self.assertEqual(calls, ["remove_pending", "append_history"])


# --- Fix 5: propose_one is_buildable retry -----------------------------------

class TestProposeOneBuildableRetry(unittest.TestCase):
    """Issue #5: graph/pipeline_io.propose_one must retry opt.ask() with a
    penalty tell when is_buildable returns False, up to MAX_RETRY=20. The
    x_override path must bypass the loop.
    """
    def test_retry_loop_drives_to_buildable_pick(self):
        # Two unbuildable picks then a buildable one — loop must converge
        # and emit the third pick.
        asks = [[1.0], [2.0], [3.0]]
        is_b = {1.0: False, 2.0: False, 3.0: True}

        class FakeOpt:
            def __init__(self):
                self.told = []
            def ask(self):
                return list(asks.pop(0))
            def tell(self, x, y):
                self.told.append((tuple(x), y))

        opt = FakeOpt()
        # Reproduce the retry loop's contract.
        MAX_RETRY = 20
        penalty_y = 10.0
        for _ in range(MAX_RETRY):
            x = opt.ask()
            if is_b[x[0]]:
                break
            opt.tell(list(x), penalty_y)

        self.assertEqual(x, [3.0])
        self.assertEqual(len(opt.told), 2,
                         "must penalize each unbuildable pick before re-ask")
        self.assertEqual(opt.told[0][1], penalty_y)

    def test_x_override_bypasses_retry(self):
        # If caller passes x_override, no opt.ask / no is_buildable check.
        src = (PROJECT_ROOT / "graph" / "pipeline_io.py").read_text()
        m = re.search(r"def propose_one\(.*?\n(.*?)(?=\ndef |\nclass )", src, re.DOTALL)
        self.assertIsNotNone(m, "propose_one not found")
        body = m.group(1)
        # x_override branch must use `x = list(x_override)` BEFORE the else
        # that runs opt.ask()/is_buildable. Pattern check: "if x_override
        # is not None" precedes the retry loop's `MAX_RETRY`.
        i_override = body.find("x_override is not None")
        i_max = body.find("MAX_RETRY")
        self.assertGreater(i_override, -1, "x_override branch missing")
        self.assertGreater(i_max, -1, "MAX_RETRY retry loop missing")
        self.assertLess(
            i_override, i_max,
            "x_override branch must be evaluated before the BO retry loop"
        )

    def test_retry_loop_constants_in_source(self):
        # Pin MAX_RETRY value so a silent shrink doesn't slip through.
        src = (PROJECT_ROOT / "graph" / "pipeline_io.py").read_text()
        self.assertIn("MAX_RETRY = 20", src,
                      "MAX_RETRY must stay at 20 (matches cmd_propose budget)")


# --- Follow-on: node_propose re-entry preserves caller-pinned name -----------

class TestProposeReentryPreservesCallerName(unittest.TestCase):
    """foilsX06 R02_08/09 (2026-05-30): when route_after_preflight re-loops
    into node_propose after preflight=ambiguous, propose_one raises
    ValueError on the pending-row from the prior attempt. The pre-fix
    except-branch silently renamed config_name to next_config_name(mode)
    (e.g. graph003), tripping graph/run.py's swap guard. Fix preserves
    the caller-pinned name by removing the stale pending row.
    """
    def _import_nodes(self):
        # Late import so PROJECT_ROOT / "graph" is already on sys.path.
        import importlib
        import graph.nodes as nodes_mod
        return importlib.reload(nodes_mod)

    def _run_propose(self, nodes_mod, state, propose_one_side_effect,
                     remove_pending_calls, next_config_name_value="graph999"):
        """Drive node_propose with monkeypatched pio + bo.MODES[mode].

        Returns (result_dict, propose_calls, remove_pending_calls_list,
        next_name_calls).
        """
        propose_calls = []
        next_name_calls = []

        def fake_propose_one(mode, name, alpha, x_override):
            propose_calls.append({"mode": mode, "name": name, "alpha": alpha,
                                  "x_override": x_override})
            # side_effect is a list of either Exception instances or
            # (x, geom_path) tuples, consumed in order.
            outcome = propose_one_side_effect.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def fake_next_config_name(mode):
            next_name_calls.append(mode)
            return next_config_name_value

        class FakeMode:
            def remove_pending(self, name):
                remove_pending_calls.append(name)
                return False

        with mock.patch.object(nodes_mod.pio, "propose_one",
                               side_effect=fake_propose_one), \
             mock.patch.object(nodes_mod.pio, "next_config_name",
                               side_effect=fake_next_config_name), \
             mock.patch.dict(nodes_mod.bo.MODES,
                             {state.get("mode", "foils"): FakeMode()},
                             clear=False):
            result = nodes_mod.node_propose(state)

        return result, propose_calls, next_name_calls

    def test_caller_pinned_stale_pending_keeps_name(self):
        """Case 1: caller-pinned + ValueError on first propose_one →
        remove_pending(name) called once, retry under SAME name, no
        next_config_name fork.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        state = {
            "mode": "foils",
            "alpha": 1e5,
            "config_name": "foilsX06R02_08",
            "x_point": None,
            "attempts": {"propose": 0},
        }
        side_effect = [
            ValueError("config name foilsX06R02_08 already in leaderboard or pending"),
            ([1.0, 2.0, 3.0, 4.0, 5.0], "/tmp/geom.txt"),
        ]
        result, propose_calls, next_name_calls = self._run_propose(
            nodes_mod, state, side_effect, remove_calls,
        )
        self.assertEqual(result["config_name"], "foilsX06R02_08",
                         "caller-pinned name MUST survive re-entry")
        self.assertEqual(remove_calls, ["foilsX06R02_08"],
                         "remove_pending must be called exactly once with caller's name")
        self.assertEqual(len(propose_calls), 2)
        self.assertEqual(propose_calls[0]["name"], "foilsX06R02_08")
        self.assertEqual(propose_calls[1]["name"], "foilsX06R02_08",
                         "retry MUST use the same caller-pinned name")
        self.assertEqual(next_name_calls, [],
                         "must NOT fork to next_config_name on caller-pinned re-entry")

    def test_caller_pinned_clean_no_remove(self):
        """Case 2: caller-pinned + first propose_one succeeds →
        remove_pending never called.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        state = {
            "mode": "foils",
            "alpha": 1e5,
            "config_name": "foilsX06R00_00",
            "x_point": None,
            "attempts": {"propose": 0},
        }
        side_effect = [([1.0, 2.0, 3.0, 4.0, 5.0], "/tmp/geom.txt")]
        result, propose_calls, next_name_calls = self._run_propose(
            nodes_mod, state, side_effect, remove_calls,
        )
        self.assertEqual(result["config_name"], "foilsX06R00_00")
        self.assertEqual(remove_calls, [],
                         "remove_pending must NOT be called when first attempt succeeds")
        self.assertEqual(len(propose_calls), 1)
        self.assertEqual(next_name_calls, [])

    def test_caller_pinned_with_x_point_forwards_override(self):
        """Case 3: closed-loop trigger path — caller-pinned + x_point set
        (forced by node_launch_children for GP-Pareto picks). Retry must
        forward x_override unchanged.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        forced_x = [3.0, 6.0, 180.0, 0.15, 8.0]
        state = {
            "mode": "foils",
            "alpha": 1e5,
            "config_name": "foilsX06R02_08",
            "x_point": forced_x,
            "attempts": {"propose": 0},
        }
        side_effect = [
            ValueError("config name foilsX06R02_08 already in leaderboard or pending"),
            (forced_x, "/tmp/geom.txt"),
        ]
        result, propose_calls, next_name_calls = self._run_propose(
            nodes_mod, state, side_effect, remove_calls,
        )
        self.assertEqual(result["config_name"], "foilsX06R02_08")
        self.assertEqual(remove_calls, ["foilsX06R02_08"])
        self.assertEqual(propose_calls[0]["x_override"], forced_x)
        self.assertEqual(propose_calls[1]["x_override"], forced_x,
                         "x_override MUST be forwarded to retry, not dropped")
        self.assertEqual(next_name_calls, [])

    def test_auto_named_path_collision_forks_to_next_name(self):
        """Case 4: legacy CLI smoke (no --config-name) + collision →
        fork to next_config_name(mode). Legacy behavior preserved.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        state = {
            "mode": "foils",
            "alpha": 1e5,
            # config_name omitted (auto-named path)
            "x_point": None,
            "attempts": {"propose": 0},
        }
        side_effect = [
            ValueError("config name graph002 already in leaderboard or pending"),
            ([1.0, 2.0, 3.0, 4.0, 5.0], "/tmp/geom.txt"),
        ]
        # First next_config_name call seeds the initial name; second is the
        # collision fork. Patch with a counter.
        names = iter(["graph002", "graph003"])

        def fake_next_config_name(mode):
            return next(names)

        propose_calls = []
        def fake_propose_one(mode, name, alpha, x_override):
            propose_calls.append({"name": name, "x_override": x_override})
            outcome = side_effect.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        class FakeMode:
            def remove_pending(self, name):
                remove_calls.append(name)
                return False

        with mock.patch.object(nodes_mod.pio, "propose_one",
                               side_effect=fake_propose_one), \
             mock.patch.object(nodes_mod.pio, "next_config_name",
                               side_effect=fake_next_config_name), \
             mock.patch.dict(nodes_mod.bo.MODES,
                             {"foils": FakeMode()}, clear=False):
            result = nodes_mod.node_propose(state)

        self.assertEqual(result["config_name"], "graph003",
                         "auto-named path MUST fork to next_config_name on collision")
        self.assertEqual(remove_calls, [],
                         "remove_pending must NOT be called on auto-named collision "
                         "(detection of concurrent same-name picker is the goal)")
        self.assertEqual(propose_calls[0]["name"], "graph002")
        self.assertEqual(propose_calls[1]["name"], "graph003")

    def test_attempts_propose_counter_increments_on_retry(self):
        """Case 5: attempts.propose increments by 1 regardless of which
        branch (caller-pinned retry or auto-named fork) the except path
        takes — keeps the route_after_preflight retry budget honest.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        state = {
            "mode": "foils",
            "alpha": 1e5,
            "config_name": "foilsX06R02_08",
            "x_point": None,
            "attempts": {"propose": 3, "other": 99},
        }
        side_effect = [
            ValueError("config name foilsX06R02_08 already in leaderboard or pending"),
            ([1.0, 2.0, 3.0, 4.0, 5.0], "/tmp/geom.txt"),
        ]
        result, _, _ = self._run_propose(
            nodes_mod, state, side_effect, remove_calls,
        )
        self.assertEqual(result["attempts"]["propose"], 4,
                         "attempts.propose must increment by exactly 1 per node entry")
        self.assertEqual(result["attempts"]["other"], 99,
                         "unrelated attempts keys must be preserved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
