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

    def test_knobs_are_foilsflash_ax_plus_three(self):
        base = [(k.name, k.min, k.max) for k in self.base.knobs]
        mine = [(k.name, k.min, k.max) for k in self.s.knobs]
        self.assertEqual(mine[:len(base)], base)
        self.assertEqual({n: (lo, hi) for n, lo, hi in mine[len(base):]},
                         NEW_KNOBS)

    def test_same_measurement_as_foilsflash_ax(self):
        """Same analyses; mubeam and mustops_ce split into twice the jobs
        at half the events, so the statistics are unchanged."""
        mine = {s.step: s for s in self.s.steps}
        base = {s.step: s for s in self.base.steps}
        self.assertEqual(list(mine), list(base))
        for name in ("elebeam_flash", "stops", "ce_edep", "sob", "flash"):
            self.assertEqual(mine[name], base[name], name)
        for name in ("mubeam", "mustops_ce"):
            m, b = mine[name].fixed, base[name].fixed
            self.assertEqual(m["njobs"], 2 * b["njobs"], name)
            self.assertEqual(m["njobs"] * m["events_per_job"],
                             b["njobs"] * b["events_per_job"], name)
        self.assertEqual(mine["mustops_ce"].entry, "mustops_ce_skip4000")
        self.assertEqual(mine["mubeam"].entry, "mubeam_earlyflash1")
        self.assertEqual(self.s.objectives, self.base.objectives)
        self.assertEqual(self.s.constraints, self.base.constraints)
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


if __name__ == "__main__":
    unittest.main()
