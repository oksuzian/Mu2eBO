"""foilsflash_col5bf_ax: foilsflash_ax plus the COL5 inner radius and the DS
and downstream-TS field scales (wiki/concepts/bfield-map-scale-patch.md).
The field scales are geometry keys only a patched GeometryService reads, so
these tests pin the patched tarball and the rendered keys."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import modes  # noqa: E402

TARBALL = "${ARTIFACT}/autoresearch_muse/Code_mdc2025ax_bfscale.tar.bz2"
SCALED_LINES = [f"BFieldManagerMaker: map {m} scaled by"
                for m in ("DSMap", "DSExtension", "TSdMap")]
NEW_KNOBS = {"col5_rIn": (80.0, 200.0), "ds_bscale": (0.75, 1.1),
             "tsd_bscale": (0.75, 1.1)}


def _geom_lines(text):
    return [ln for ln in text.splitlines() if ln and not ln.startswith("//")]


class TestFoilsflashCol5bf(unittest.TestCase):
    def setUp(self):
        self.s = modes.STUDIES["foilsflash_col5bf_ax"]
        self.base = modes.STUDIES["foilsflash_ax"]

    def test_both_kits_run_the_patched_tarball(self):
        """Stock Offline ignores bfield.mapScale.*: the jobs and the
        pre-check must both run the patched build."""
        kits = json.loads(self.s.path.read_text())["kits"]
        self.assertEqual(kits["prodtools"]["code_tarball"], TARBALL)
        self.assertEqual(kits["offline_preflight"]["code_tarball"], TARBALL)

    def test_every_grid_job_must_print_the_applied_scales(self):
        """Stock Offline ignores bfield.mapScale.* silently: each prodtools
        job's log must show the patched build scaled every rendered map."""
        for step in self.s.steps:
            if step.kit == "prodtools":
                self.assertEqual(step.fixed["required_log_lines"],
                                 SCALED_LINES, step.step)
        rendered = {ln.split()[1].removeprefix("bfield.mapScale.")
                    for ln in _geom_lines(self.s.geom.render(
                        [150.0, 120.0, 0.05, 0.08, 0.3, 0.4, 175.5, 0.8, 1.05]))
                    if "bfield.mapScale." in ln}
        self.assertEqual({f"BFieldManagerMaker: map {m} scaled by"
                          for m in rendered}, set(SCALED_LINES))

    def test_anakit_runs_a_release_with_the_edep_step_counts(self):
        """The *_steps metrics need EdepAna's step counts (Offline #2067)."""
        kits = json.loads(self.s.path.read_text())["kits"]
        self.assertEqual(kits["anakit"]["musing"], "Offline v13_43_00")

    def test_knobs_are_foilsflash_ax_plus_three(self):
        base = [(k.name, k.min, k.max) for k in self.base.knobs]
        mine = [(k.name, k.min, k.max) for k in self.s.knobs]
        self.assertEqual(mine[:len(base)], base)
        self.assertEqual({n: (lo, hi) for n, lo, hi in mine[len(base):]},
                         NEW_KNOBS)

    def test_the_steps(self):
        """foilsflash_ax's steps and statistics; mubeam and mustops_ce run as
        50 shorter jobs with the same total events; then the mu-beam flash,
        the mu-stop pileup and their sum with the e-beam flash."""
        mine = {s.step: s for s in self.s.steps}
        base = {s.step: s for s in self.base.steps}
        self.assertEqual(list(mine), ["mubeam", "mustops_ce", "mustops_pileup",
                                      "elebeam_flash", "stops", "ce_edep",
                                      "sob", "flash", "muflash", "pileup",
                                      "dose"])
        for name in ("ce_edep", "sob", "flash"):
            self.assertEqual(mine[name], base[name], name)
        flash = dict(mine["elebeam_flash"].fixed)
        self.assertEqual(flash.pop("required_log_lines"), SCALED_LINES)
        self.assertEqual(flash, base["elebeam_flash"].fixed)
        stops = dict(mine["stops"].fixed)
        self.assertEqual(stops.pop("input_glob"), "sim.*.TargetStops.*.art")
        self.assertEqual(stops, base["stops"].fixed)
        for name in ("mubeam", "mustops_ce"):
            m, b = mine[name].fixed, base[name].fixed
            self.assertEqual(m["njobs"], 50, name)
            self.assertEqual(m["njobs"] * m["events_per_job"],
                             b["njobs"] * b["events_per_job"], name)
        self.assertEqual(mine["mubeam"].entry, "mubeam_earlyflash1")
        self.assertEqual(mine["mustops_ce"].entry, "mustops_ce_skip2000")

    def test_the_skip_stays_well_below_the_stops_per_mubeam_file(self):
        """Each CE and pileup job reads one mubeam file; a random skip past
        its end fails the job. 0.088 stops per beam event was the lowest on
        the foilspfbpz_ax optchk points: keep a factor 2 of margin."""
        per_file = 0.088 * {s.step: s for s in self.s.steps}[
            "mubeam"].fixed["events_per_job"]
        for entry in ("mustops_ce_skip2000", "mustops_pileup"):
            t = json.loads((ROOT / "stage_entries" / f"{entry}.json")
                           .read_text())
            skip = t["fcl_overrides"][
                "physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip"]
            self.assertLessEqual(2 * skip, per_file, entry)
            self.assertEqual(t["input_glob"], "sim.*.TargetStops.*.art")

    def test_the_extra_measurements(self):
        """The mu-beam flash and the muon-stop pileup are measured, not
        optimized: each source's edep and step counts (the edep-based
        occupancy estimate) are extra metrics."""
        mine = {s.step: s for s in self.s.steps}
        self.assertEqual(mine["muflash"].fixed,
                         {"analysis": "edep",
                          "input_glob": "dts.*.EarlyMuBeamFlash.*.art"})
        self.assertEqual(mine["pileup"].files_from, ("mustops_pileup",))
        metrics = {m.name: m.metric for m in self.s.extra_metrics}
        for src in ("muflash", "pileup"):
            for q, key in (("trk_edep", "avg_trk_edep_per_gen_event_mev"),
                           ("calo_edep", "avg_calo_edep_per_gen_event_mev"),
                           ("trk_steps", "trk_nsteps_ecut_tcut_per_gen_event"),
                           ("calo_steps",
                            "calo_nsteps_ecut_tcut_per_gen_event")):
                self.assertEqual(metrics[f"{src}_{q}"], f"{src}.{key}")
        self.assertEqual(metrics["stops_per_pot"], "stops.stops_per_pot")
        self.assertEqual({c.name for c in self.s.extra_columns} - {"alpha", "obj"},
                         {"calo_edep_per_pot", "trk_steps_per_pot",
                          "calo_steps_per_pot"})
        self.assertEqual(metrics["flash_edep"],
                         "flash.avg_trk_edep_per_gen_event_mev")

    def test_the_dose_objective_is_the_total_per_pot(self):
        """sob as in foilsflash_ax; the dose is anakit's sum of the three
        sources' tracker deposition per POT, fed by params_from only."""
        base = {o.name: o for o in self.base.objectives}
        mine = {o.name: o for o in self.s.objectives}
        self.assertEqual(list(mine), ["sob", "dose"])
        self.assertEqual(mine["sob"], base["sob"])
        self.assertEqual((mine["dose"].metric, mine["dose"].direction,
                          mine["dose"].transform),
                         ("dose.total_edep_per_pot_mev", "min", "log10"))
        dose = {s.step: s for s in self.s.steps}["dose"]
        self.assertEqual(dose.fixed, {"analysis": "total_edep_per_pot"})
        self.assertEqual(dose.files_from, ())
        self.assertEqual(dose.params_from, {
            "ebeam_edep_per_gen_event_mev": "flash.avg_trk_edep_per_gen_event_mev",
            "mubeam_edep_per_gen_event_mev": "muflash.avg_trk_edep_per_gen_event_mev",
            "mustop_edep_per_gen_event_mev": "pileup.avg_trk_edep_per_gen_event_mev",
            "stops_per_pot": "stops.stops_per_pot"})
        # the e-beam-only budget does not bound the total: none until
        # foilsflash_col5bf_nominal has measured the deployed target's dose
        self.assertEqual(self.s.constraints, ())
        self.assertNotEqual(self.s.leaderboard_rel, self.base.leaderboard_rel)

    def test_the_geometry_adds_col5_and_the_field_scales(self):
        foils = [150.0, 120.0, 0.05, 0.08, 0.3, 0.4]
        mine = _geom_lines(self.s.geom.render(foils + [175.5, 0.8, 1.05]))
        base = _geom_lines(self.base.geom.render(foils))
        self.assertTrue(set(base) <= set(mine))
        self.assertEqual(sorted(set(mine) - set(base)), sorted([
            "double ts.coll5.Radius1 = 175.5000;",
            "double bfield.mapScale.DSMap = 0.800000;",
            "double bfield.mapScale.DSExtension = 0.800000;",
            "double bfield.mapScale.TSdMap = 1.050000;"]))


class TestFoilsflashCol5bfNominal(unittest.TestCase):
    """The deployed target in foilsflash_col5bf_ax's environment: its dose
    is the total-dose budget."""

    def setUp(self):
        self.s = modes.STUDIES["foilsflash_col5bf_nominal"]
        self.study = modes.STUDIES["foilsflash_col5bf_ax"]

    def test_it_measures_what_the_study_measures(self):
        self.assertEqual(self.s.knobs, ())
        for field in ("steps", "objectives", "extra_metrics", "kits",
                      "preflight"):
            self.assertEqual(getattr(self.s, field),
                             getattr(self.study, field), field)
        self.assertEqual([c.expr for c in self.s.extra_columns],
                         [c.expr for c in self.study.extra_columns])
        self.assertNotEqual(self.s.leaderboard_rel, self.study.leaderboard_rel)

    def test_the_geometry_is_the_deployed_target_at_nominal_fields(self):
        lines = _geom_lines(self.s.geom.render([]))
        for want in ("double ts.coll5.Radius1 = 128.0;",
                     "double bfield.mapScale.DSMap = 1.0;",
                     "double bfield.mapScale.DSExtension = 1.0;",
                     "double bfield.mapScale.TSdMap = 1.0;"):
            self.assertIn(want, lines)
        radii = next(ln for ln in lines if "stoppingTarget.radii" in ln)
        self.assertEqual(radii.count("75.0000"), 37)
        nominal = _geom_lines(modes.STUDIES["foilspf_nominal"].geom.render([]))
        self.assertTrue(set(nominal) <= set(lines))


if __name__ == "__main__":
    unittest.main()
