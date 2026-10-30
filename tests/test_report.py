"""core/report.py and its two callers: the loop-exit report graph.closed_loop
starts by itself, and start_report, the driving agent's mid-campaign one.
The reporter is tests/fixtures/fake_reporter (no model, no network)."""
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import report  # noqa: E402
from campaign_dir import CampaignDir  # noqa: E402
from tests.engine_fixtures import (ENGINE_STUDIES, FAKE_REPORTER,  # noqa: E402
                                   EngineCase, TmpCase, engine_env)

LOCAL = ["--picker", "budget_sob", "--executor", "local", "--parallel", "1"]


def wait_done(camp_path, n=1, timeout=60):
    deadline = time.time() + timeout
    while True:
        reps = report.reports(camp_path)
        if len(reps) >= n and all(r["state"] != "running" for r in reps):
            return reps
        if time.time() > deadline:
            raise AssertionError(f"reports never finished: {reps}")
        time.sleep(0.1)


class TestReportJob(TmpCase):
    def setUp(self):
        super().setUp()
        self.camp = self.tmp / "data" / "autoresearch_graph_data" / "pfx"
        self.camp.mkdir(parents=True)
        self.env = {**os.environ, "AUTORESEARCH_REPORTER": str(FAKE_REPORTER)}

    def test_a_report_runs_and_reads_back(self):
        info = report.start(self.camp, "branin", "exit", note="rc 0", env=self.env)
        (r,) = wait_done(self.camp)
        self.assertEqual((r["report_id"], r["trigger"], r["state"], r["exit_code"], r["checked"]),
                         (info["report_id"], "exit", "done", 0, True))
        self.assertEqual(r["unsupported"], 0)
        self.assertIn("fake report pfx (exit)", Path(r["report"]).read_text())
        argv = (Path(info["dir"]) / "out" / "argv.txt").read_text().split("\n")
        self.assertEqual(argv[argv.index("--data-root") + 1], str(self.tmp / "data"))
        self.assertEqual(argv[argv.index("--note") + 1], "rc 0")

    def test_a_flagged_report_is_done_but_not_checked(self):
        report.start(self.camp, "branin", "milestone", env={**self.env, "FAKE_REPORTER_RC": "1"})
        (r,) = wait_done(self.camp)
        self.assertEqual((r["state"], r["exit_code"], r["checked"]), ("done", 1, False))

    def test_running_then_lost(self):
        info = report.start(self.camp, "branin", "exit", env={**self.env, "FAKE_REPORTER_SLEEP": "30"})
        self.assertEqual(report.reports(self.camp)[0]["state"], "running")
        os.killpg(info["pid"], 9)
        deadline = time.time() + 20
        while report.reports(self.camp)[0]["state"] == "running":
            self.assertLess(time.time(), deadline)
            time.sleep(0.1)
        self.assertEqual(report.reports(self.camp)[0]["state"], "lost")

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, "AUTORESEARCH_REPORTER is not set"):
            report.start(self.camp, "branin", "exit", env={})
        with self.assertRaisesRegex(ValueError, "not a mu2ebo-reporter checkout"):
            report.start(self.camp, "branin", "exit", env={"AUTORESEARCH_REPORTER": str(self.tmp)})
        with self.assertRaisesRegex(ValueError, "trigger"):
            report.start(self.camp, "branin", "whenever", env=self.env)
        self.assertEqual(report.reports(self.camp), [])


class TestLoopExitReport(EngineCase):
    """Every campaign ends with a report, started by closed_loop itself."""

    def loop(self, prefix, *extra, env=None):
        return subprocess.run(
            [sys.executable, "-m", "graph.closed_loop", "--study", "branin", "--q", "1",
             "--max-evals", "1", "--name-prefix", prefix, *LOCAL, *extra],
            cwd=ROOT, env=env or engine_env(self.data, ENGINE_STUDIES),
            capture_output=True, text=True, timeout=180)

    def camp(self, prefix):
        return CampaignDir(self.data / "autoresearch_graph_data", prefix).path

    def test_the_loop_exit_starts_the_final_report(self):
        r = self.loop("rpt")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertIn("[closed_loop] final report started", r.stdout)
        (rp,) = wait_done(self.camp("rpt"))
        self.assertEqual((rp["trigger"], rp["state"], rp["checked"]), ("exit", "done", True))
        self.assertEqual(rp["note"], "closed_loop exit code 0")
        self.assertTrue(CampaignDir(self.data / "autoresearch_graph_data", "rpt").record()["report"])

    def test_no_report_skips_it(self):
        r = self.loop("nor", "--no-report")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertNotIn("final report", r.stdout)
        self.assertEqual(report.reports(self.camp("nor")), [])

    def test_a_missing_reporter_is_a_warning_not_a_refusal(self):
        env = engine_env(self.data, ENGINE_STUDIES)
        env.pop("AUTORESEARCH_REPORTER")
        r = self.loop("mis", env=env)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertIn("[closed_loop] WARNING: no final report at loop exit: "
                      "AUTORESEARCH_REPORTER is not set", r.stdout)
        self.assertNotIn("final report started", r.stdout)
        self.assertNotIn("REFUSED", r.stdout)
        self.assertEqual(report.reports(self.camp("mis")), [])
        rec = CampaignDir(self.data / "autoresearch_graph_data", "mis").record()
        self.assertFalse(rec["report"])
        r = self.loop("mis2", "--check-only", env=env)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:])
        self.assertIn("WARNING: no final report", r.stdout)
        r = self.loop("mis3", "--check-only", "--no-report", env=env)
        self.assertNotIn("WARNING", r.stdout)


class TestReportWhenThePoolRaises(EngineCase):
    def test_a_raising_pool_still_reports(self):
        import closed_loop
        import study as st
        started = []
        with mock.patch.object(closed_loop.paths, "GRAPH_DATA", self.data / "autoresearch_graph_data"), \
                mock.patch.dict(closed_loop._modes.STUDIES,
                                {"branin": st.load_study_file(ENGINE_STUDIES / "branin.json")}), \
                mock.patch.object(closed_loop, "launch_problems", return_value=[]), \
                mock.patch.object(closed_loop, "KitSet", return_value=mock.MagicMock()), \
                mock.patch.object(closed_loop, "run_rolling", side_effect=RuntimeError("pool")), \
                mock.patch.object(closed_loop._report, "start",
                                  side_effect=lambda *a, **k: started.append((a, k)) or {"dir": "d"}):
            with self.assertRaises(RuntimeError):
                closed_loop.main(["--study", "branin", "--q", "1", "--max-evals", "1",
                                  "--name-prefix", "rse", "--stagger", "0", *LOCAL])
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][0][1:3], ("branin", "exit"))
        self.assertEqual(started[0][1]["note"], "closed_loop exit code 1")

    def test_a_report_that_cannot_start_does_not_change_the_exit_code(self):
        import closed_loop
        logged = []
        camp = CampaignDir(self.data / "g", "x")
        with mock.patch.object(closed_loop._report, "start", side_effect=OSError("quota")):
            self.assertIsNone(closed_loop.final_report(camp, "branin", 0,
                                                       log=lambda m, **k: logged.append(m)))
        self.assertIn("final report not started: quota", logged[0])


class TestStartReport(EngineCase):
    def setUp(self):
        super().setUp()
        from service.campaigns import CampaignService
        self.env = engine_env(self.data, ENGINE_STUDIES)
        self.svc = CampaignService(env=self.env)
        self.cd = CampaignDir(self.data / "autoresearch_graph_data", "mil")

    def test_a_milestone_report_and_its_text(self):
        with self.cd.start({"study": "branin"}):
            info = self.svc.start_report("mil", note="first rows")
            (r,) = wait_done(self.cd.path)
            st = self.svc.campaign_status("mil")
        self.assertEqual([x["report_id"] for x in st["reports"]], [info["report_id"]])
        self.assertEqual(r["trigger"], "milestone")
        out = self.svc.report_text("mil", info["report_id"])
        self.assertIn("fake report mil (milestone)", out["text"])
        self.assertEqual(out["note"], "first rows")

    def test_one_at_a_time_and_refusals(self):
        with self.assertRaisesRegex(ValueError, "no campaign record"):
            self.svc.start_report("mil")
        with self.cd.start({"study": "branin"}):
            self.svc.env["FAKE_REPORTER_SLEEP"] = "30"
            info = self.svc.start_report("mil")
            with self.assertRaisesRegex(ValueError, "still running"):
                self.svc.start_report("mil")
            os.killpg(info["pid"], 9)
        with self.assertRaisesRegex(ValueError, "no report"):
            self.svc.report_text("mil", "nope")


if __name__ == "__main__":
    unittest.main()
