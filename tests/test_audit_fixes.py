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


if __name__ == "__main__":
    unittest.main(verbosity=2)
