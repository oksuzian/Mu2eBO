"""The facts each KitDecl states about the params its kit receives."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import kit_registry  # noqa: E402
from adapters import anakit, prodtools  # noqa: E402

KITS = kit_registry.KITS
ADAPTERS = ("prodtools", "offline_preflight", "anakit", "beamkit")


class TestKitDecls(unittest.TestCase):
    def test_own_params_are_todays_lists(self):
        for kit, own in (
                ("prodtools", ("entry", "code_tarball", "dsconf",
                               "fatal_log_codes", "njobs", "events_per_job",
                               "memory_mb", "quorum")),
                ("beamkit", ("deck_url", "deck_ref", "main_input",
                             "deck_params", "njobs", "events_per_job",
                             "quorum", "plane", "pdg")),
                ("anakit", ("musing", "analysis")),
                ("offline_preflight", ("code_tarball", "dumps_gdml",
                                       "verifies_foil_gdml",
                                       "checks_managed_overlap",
                                       "require_zero_overlaps")),
                ("toykit", ("function",))):
            with self.subTest(kit=kit):
                self.assertEqual(KITS[kit].own_params, own)

    def test_the_adapters_read_their_own_params(self):
        self.assertEqual(prodtools.PARAMS, KITS["prodtools"].own_params)
        self.assertEqual(anakit.OWN_PARAMS, KITS["anakit"].own_params)
        # beamkit's deck_params may not hold a name the adapter reads
        for name in KITS["beamkit"].own_params:
            with self.subTest(name=name), self.assertRaises(ValueError) as cm:
                kit_registry._deck_params({name: 1}, "w")
            self.assertIn("set by beamkit's worker or the adapter",
                          str(cm.exception))

    def test_no_kit_shares_a_settings_and_a_fixed_key(self):
        for name, decl in KITS.items():
            with self.subTest(kit=name):
                self.assertEqual(set(decl.study_keys) & set(decl.fixed_keys),
                                 set())

    def test_the_new_facts(self):
        for name in ADAPTERS + ("toykit",):
            with self.subTest(kit=name):
                self.assertIs(KITS[name].accepts_lists, False)
        self.assertEqual(KITS["anakit"].passes_on,
                         {"upstream_eff", "cosmic_rate_per_s_per_mev",
                          "trigger_paths"})
        self.assertEqual(KITS["toykit"].passes_on,
                         frozenset(KITS["toykit"].fixed_keys))
        beamkit = KITS["beamkit"]
        self.assertEqual(beamkit.inner_params_setting, "deck_params")
        self.assertTrue(beamkit.param_name_pattern.fullmatch("R_1"))
        self.assertIsNone(beamkit.param_name_pattern.fullmatch("1R"))
        for name, decl in KITS.items():
            if name != "beamkit":
                with self.subTest(kit=name):
                    self.assertIsNone(decl.inner_params_setting)
                    self.assertIsNone(decl.param_name_pattern)


if __name__ == "__main__":
    unittest.main()
