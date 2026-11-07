"""foilsnopa_bc (no IPA, no OPA, 6 + 6 extra foils, a target shift; S/sqrt(B)
and the busiest tracker-region hit rate) and its with-absorber twin
foilsflash_bc, both on SimJob MDC2025bc. Spec:
docs/superpowers/specs/2026-10-30-foilsnopa-study-design.md (local),
revision 2026-11-05."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import modes  # noqa: E402

MODES = ROOT / "mode_specs"
KNOBS = ("extra_rOut_up", "extra_rOut_dn", "extra_halfThickness_up",
         "extra_halfThickness_dn", "extra_f_up", "extra_f_dn", "target_dz")
X_MID = [150.0, 150.0, 0.501, 0.501, 0.475, 0.475, 950.0]
TARBALL = "${ARTIFACT}/autoresearch_muse/Code_mdc2025bc.tar.bz2"
STOPS = "mubeam:sim.*.TargetStops.*.art"
SAMPLES = ["mubeam", "mustops_ce", "elebeam_flash", "mustops_pileup", "stops",
           "ce_edep", "sob", "flash"]
OCC = ["pileup_occ", "eflash_occ", "muflash_occ", "occupancy"]
POT_PER_MB = 1.58e7         # SimEfficiencies2 Sim_best v1_1, the tool's default
# The busiest 12-plane x 8-straw region (analysis-mcp v01_03_00): unbiased at a
# design point's statistics, 3.3% statistical error on nopa01 (split test).
REGION = {"region_planes": 12, "region_straws": 8}
MAX_HIT = "occupancy.trk_peak_region_hit_rate_khz"
SAVED = ["max_hit_rate_err", "max_hit_plane", "max_hit_radius", "peak_row_rate",
         "peak_straw_rate", "mean_hit_rate", "max_edep_rate", "max_calo_rate",
         "hits_per_mb", "hits_per_mb_stopped_mu", "hits_per_mb_ele_flash",
         "hits_per_mb_mu_flash"]


def _study(name):
    return modes.STUDIES[name]


def _doc(name):
    return json.loads((MODES / f"{name}.json").read_text())


def _render(x):
    return _study("foilsnopa_bc").geom.render(x)


def _vec(text, key):
    prefix = f"vector<double> {key} = {{"
    for line in text.splitlines():
        if line.startswith(prefix):
            return [float(v) for v in line[len(prefix):].rsplit("}", 1)[0].split(",")]
    raise KeyError(key)


def _keys(text):
    return {ln.split(" = ")[0].split(" ", 1)[1]: ln.split(" = ")[1].rstrip(";")
            for ln in text.splitlines()
            if ln.strip() and not ln.startswith(("//", "#")) and " = " in ln}


class TestFoilsnopaGeometry(unittest.TestCase):
    def test_knobs_and_bounds(self):
        s = _study("foilsnopa_bc")
        self.assertEqual(s.knob_names, KNOBS)
        dz = s.knobs[-1]
        self.assertEqual((dz.min, dz.max), (0.0, 1900.0))

    def test_no_ipa_vacuum_opa_and_no_supports(self):
        """Offline v13_44_00 builds hasProtonAbsorber=false (PR #2089), but
        without the outer absorber ST_In, ST_Out and STMUpstream span the DS2
        bore minus 5 mm (constructVirtualDetectors.cc) and overlap
        Coupler_DS2_1, so the IPA is not built, the OPA is DS vacuum and its
        supports are off."""
        keys = _keys(_render(X_MID))
        self.assertNotIn("hasProtonAbsorber", keys)
        self.assertEqual({k: v for k, v in keys.items() if k.startswith("protonabsorber.")}, {
            "protonabsorber.ipa.build": "false",
            "protonabsorber.outerPAMaterialName": '"DSVacuum"',
            "protonabsorber.oPASupportNSupportRing": "0",
            "protonabsorber.zStartInMu2e": "6901.02"})

    def test_target_shift(self):
        for dz, z0 in ((0.0, "5871.0000"), (950.0, "6821.0000"), (1900.0, "7771.0000")):
            with self.subTest(target_dz=dz):
                self.assertEqual(_keys(_render(X_MID[:6] + [dz]))["stoppingTarget.z0InMu2e"], z0)

    def test_49_foils_and_poison_pill(self):
        text = _render(X_MID)
        for key in ("stoppingTarget.radii", "stoppingTarget.halfThicknesses",
                    "stoppingTarget.holeRadii"):
            self.assertEqual(len(_vec(text, key)), 49, key)
        self.assertIn("double stoppingTarget.holeRadius = 1.0e6;", text)

    def test_no_geometry_key_twice(self):
        keys = [ln.split(" = ")[0].split(" ", 1)[1]
                for ln in _render(X_MID).splitlines()
                if ln.strip() and not ln.startswith(("//", "#"))]
        self.assertEqual(sorted(keys), sorted(set(keys)))


class TestFoilsnopaSteps(unittest.TestCase):
    def test_sample_steps(self):
        steps = {s.step: s for s in _study("foilsnopa_bc").steps}
        self.assertEqual(list(steps), SAMPLES + OCC)
        self.assertEqual(steps["mubeam"].entry, "mubeam_dts")
        for name in ("mustops_ce", "mustops_pileup", "stops"):
            self.assertEqual(steps[name].files_from, (STOPS,), name)
        self.assertEqual(steps["mustops_pileup"].fixed,
                         {"njobs": 20, "events_per_job": 50000, "memory_mb": 3000,
                          "quorum": 0.8})
        self.assertEqual(steps["sob"].params_from, {"stops_per_pot": "stops.stops_per_pot"})

    def test_occupancy_steps(self):
        steps = {s.step: s for s in _study("foilsnopa_bc").steps}
        want = {"pileup_occ": (("mustops_pileup",), "stopped_mu"),
                "eflash_occ": (("elebeam_flash",), "ele_flash"),
                "muflash_occ": (("mubeam:dts.*.EarlyMuBeamFlash.*.art",), "mu_flash")}
        for name, (files_from, label) in want.items():
            with self.subTest(step=name):
                s = steps[name]
                self.assertEqual(s.files_from, files_from)
                self.assertEqual(s.fixed["analysis"], "edep_occupancy")
                self.assertEqual(s.fixed["label"], label)
                self.assertEqual(s.fixed["pot_per_microbunch"], POT_PER_MB)
                self.assertNotIn("events_per_microbunch", s.fixed)
        # generated events per POT: stops per POT from the design's own mubeam
        # (both muon streams resample MuBeamCat.Run1Baa), one EleBeamCat event
        # per 11.5367 POT, and MuBeamCat's upstream efficiency
        self.assertEqual(steps["pileup_occ"].params_from,
                         {"gen_events_per_pot": "stops.stops_per_pot"})
        self.assertEqual(steps["eflash_occ"].fixed["gen_events_per_pot"],
                         1 / 11.536718606512062)
        self.assertEqual(steps["muflash_occ"].fixed["gen_events_per_pot"], 0.01278168)
        combine = steps["occupancy"]
        self.assertEqual(combine.fixed, {"analysis": "edep_occupancy_combine", **REGION})
        self.assertEqual(combine.files_from,
                         tuple(f"{n}:occupancy_per_microbunch.root" for n in OCC[:3]))

    def test_objectives_and_saved_columns(self):
        s = _study("foilsnopa_bc")
        self.assertEqual([(o.name, o.metric, o.direction, o.transform) for o in s.objectives],
                         [("sob", "sob.sensitivity", "max", "none"),
                          ("max_hit_rate", MAX_HIT, "min", "log10")])
        self.assertEqual(_doc("foilsnopa_bc")["objectives"][1]["noise"], 0.014)
        self.assertEqual(s.constraints, ())
        self.assertEqual([m.name for m in s.extra_metrics],
                         SAVED + ["flash_edep", "stops_per_pot"])

    def test_release_is_mdc2025bc_and_its_own_board(self):
        doc = _doc("foilsnopa_bc")
        kits = doc["kits"]
        self.assertEqual(kits["prodtools"]["code_tarball"], TARBALL)
        self.assertEqual(kits["offline_preflight"]["code_tarball"], TARBALL)
        self.assertEqual(kits["prodtools"]["dsconf"], "MDC2025bc_{cfg}")
        self.assertEqual(kits["anakit"], {"musing": "SimJob MDC2025bc"})
        self.assertEqual(doc["leaderboard"]["file"],
                         "leaderboards/leaderboard_bo_foilsnopa_bc.tsv")


class TestFoilsflashBc(unittest.TestCase):
    def test_foilsflash_bc_keeps_foilsflash_ax_physics(self):
        ax, fc, nc = _doc("foilsflash_ax"), _doc("foilsflash_bc"), _doc("foilsnopa_bc")
        for key in ("knobs", "derive", "geom", "objectives", "constraints",
                    "extra_columns"):
            self.assertEqual(fc[key], ax[key], key)
        self.assertEqual(fc["kits"], nc["kits"])
        a = {s["step"]: s for s in ax["evaluate"]}
        c = {s["step"]: s for s in fc["evaluate"]}
        n = {s["step"]: s for s in nc["evaluate"]}
        self.assertEqual(list(c), SAMPLES + OCC)
        for name in ("elebeam_flash", "ce_edep", "sob", "flash"):
            self.assertEqual(c[name], a[name], name)
        for name in ("mustops_ce", "stops"):
            self.assertEqual(dict(c[name], files_from=a[name]["files_from"]), a[name], name)
            self.assertEqual(c[name]["files_from"], [STOPS])
        self.assertEqual(dict(c["mubeam"], entry="mubeam"), a["mubeam"])
        for name in ["mustops_pileup"] + OCC:
            self.assertEqual(c[name], n[name], name)
        # max_hit_rate is foilsnopa_bc's objective; the twin saves it as a column
        extra = _study("foilsflash_bc").extra_metrics
        self.assertEqual([m.name for m in extra], ["max_hit_rate"] + SAVED + ["stops_per_pot"])
        self.assertEqual(extra[0].metric, MAX_HIT)
        self.assertEqual(fc["leaderboard"]["file"],
                         "leaderboards/leaderboard_bo_foilsflash_bc.tsv")


if __name__ == "__main__":
    unittest.main()
