"""core/kit_params.py: the names a kit receives, the rules on them, and
their values at one point."""
import copy
import dataclasses
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import kit_params as kp  # noqa: E402
import kit_registry  # noqa: E402
import paths  # noqa: E402
import study as st  # noqa: E402
from tests.engine_fixtures import ENGINE_STUDIES, TmpCase, write_study  # noqa: E402

BRANIN = json.loads((ENGINE_STUDIES / "branin.json").read_text())
PTG4BL = json.loads((ROOT / "mode_specs" / "ptg4bl.json").read_text())
DEMO = json.loads((ROOT / "tests" / "fixtures" / "studies" / "demo.json")
                  .read_text())
GEOM = {"writer": "offline_simpleconfig",
        "base": "Offline/Mu2eG4/geom/geom_run1_a.txt", "lines": []}


def toy_step(name="toy", params=None, params_from=None):
    return {"step": name, "kit": "toykit", "entry": None, "files": [],
            "files_from": [], "params": dict(params or {}),
            "params_from": dict(params_from or {}),
            "fixed": {"delay_s": 0.0}}


def profile_doc(*steps, count=3):
    """branin plus knobs c0..c2 in [0, 1] and a profile `prof` over them;
    `steps` replace its evaluate list."""
    doc = copy.deepcopy(BRANIN)
    doc["name"] = "kptest"
    doc["leaderboard"]["file"] = "leaderboards/leaderboard_kptest.tsv"
    doc["knobs"] += [{"name": c, "type": "real", "min": 0.0, "max": 1.0,
                      "unit": "", "fmt": "{:.4f}"} for c in ("c0", "c1", "c2")]
    doc["derive"]["profiles"]["prof"] = {
        "kind": "lagrange", "count": count, "control": ["c0", "c1", "c2"],
        "clip": [0.0, 1.0]}
    doc["geom"] = copy.deepcopy(GEOM)
    doc["evaluate"] = list(steps)
    return doc


def ptg_profile_doc():
    """ptg4bl with its three radius knobs replaced by the control knobs of
    a profile Rp, mapped as R, and deck_params.R_1 also set (E1)."""
    doc = copy.deepcopy(PTG4BL)
    doc["name"] = "ptgkp"
    doc["leaderboard"]["file"] = "leaderboards/leaderboard_ptgkp.tsv"
    doc["knobs"] = [k for k in doc["knobs"] if k["name"] == "Tlength"] + [
        {"name": c, "type": "real", "min": 1.5, "max": 6.0, "unit": "mm",
         "fmt": "{:.4f}"} for c in ("Rc0", "Rc1", "Rc2")]
    doc["derive"]["profiles"]["Rp"] = {
        "kind": "lagrange", "count": 3, "control": ["Rc0", "Rc1", "Rc2"],
        "clip": [1.5, 6.0]}
    doc["geom"] = copy.deepcopy(GEOM)
    doc["evaluate"][0]["params"] = {"Tlength": "Tlength", "R": "Rp"}
    doc["kits"]["beamkit"]["deck_params"]["R_1"] = 9.99
    return doc


class _Case(TmpCase):
    def load(self, doc):
        return st.load_study_file(write_study(doc, self.tmp / "studies"))

    def assertProblem(self, study, *needles):
        found = kp.problems(study)
        self.assertTrue(any(all(n in p for n in needles) for p in found),
                        f"no problem holds {needles}: {found}")
        return next(p for p in found if all(n in p for n in needles))


class TestNames(_Case):
    def test_names_split_a_profile_in_place(self):
        s = self.load(profile_doc(toy_step(params={"a": "x1", "r": "prof"})))
        found = kp.names(s, kp.sender_of(s.steps[0]))
        self.assertEqual(list(found), ["a", "r_0", "r_1", "r_2", "function",
                                       "delay_s"])
        self.assertEqual(found["r_1"], (kp.Origin("profile", "params.r",
                                                  "prof", 1),))
        self.assertEqual(found["a"], (kp.Origin("point", "params.a", "x1",
                                                None),))

    def test_a_const_count_is_resolved(self):
        doc = profile_doc(toy_step(params={"r": "prof"}), count="N")
        doc["derive"]["consts"]["N"] = 2
        s = self.load(doc)
        self.assertEqual(s.profile_counts, {"prof": 2})
        found = kp.names(s, kp.sender_of(s.steps[0]))
        self.assertEqual([n for n in found if n.startswith("r")],
                         ["r_0", "r_1"])

    def test_a_kit_that_takes_lists_gets_the_profile_whole(self):
        s = self.load(profile_doc(toy_step(params={"r": "prof"})))
        lists = dataclasses.replace(kit_registry.KITS["toykit"],
                                    accepts_lists=True)
        with mock.patch.dict(kit_registry.KITS, {"toykit": lists}):
            sender = kp.sender_of(s.steps[0])
            found = kp.names(s, sender)
            self.assertEqual(found["r"], (kp.Origin("profile", "params.r",
                                                    "prof", None),))
            env = {"prof": [0.1, 0.2, 0.3]}
            self.assertEqual(kp.build(s, sender, env, {})["r"],
                             [0.1, 0.2, 0.3])

    def test_kit_names_is_the_union_of_the_kits_senders(self):
        doc = copy.deepcopy(BRANIN)
        doc["preflight"] = {"kit": "toykit", "params": {"x1": "x1"},
                            "files": []}
        s = self.load(doc)
        self.assertEqual(kp.kit_names(s, "toykit"),
                         {"x1", "x2", "function", "delay_s"})


class TestRules(_Case):
    def test_e8_a_profile_element_and_a_knob_send_one_name(self):
        s = self.load(profile_doc(toy_step(params={"r": "prof",
                                                   "r_1": "x1"})))
        self.assertProblem(s, "'r_1'", "exactly one source",
                           "profile 'prof' element 1 (params.r)",
                           "params.r_1 = 'x1'")

    def test_e2_a_profile_element_and_params_from_send_one_name(self):
        s = self.load(profile_doc(
            toy_step("up"),
            toy_step("toy", params={"r": "prof"},
                     params_from={"r_1": "up.branin"})))
        self.assertProblem(s, "'r_1'", "params_from.r_1")

    def test_e3_a_preflight_param_and_a_setting_send_one_name(self):
        doc = copy.deepcopy(BRANIN)
        doc["preflight"] = {"kit": "toykit", "params": {"function": "x1"},
                            "files": []}
        s = self.load(doc)
        self.assertProblem(s, "[preflight.params.function]",
                           "kits.toykit.function")

    def test_e1_a_split_profile_element_and_a_deck_param(self):
        s = self.load(ptg_profile_doc())
        self.assertProblem(s, "'R_1'", "kits.beamkit.deck_params.R_1")

    def test_a_split_name_is_reported_at_its_json_key(self):
        s = self.load(ptg_profile_doc())
        p = self.assertProblem(s, "'R_1'")
        self.assertTrue(p.startswith(
            "[evaluate.g4bl.params.R]: profile 'Rp' element 1"), p)

    def test_e6_a_mapped_job_count(self):
        doc = copy.deepcopy(DEMO)
        doc["evaluate"][0]["params"] = {"njobs": "a"}
        del doc["evaluate"][0]["fixed"]["njobs"]
        s = self.load(doc)
        self.assertProblem(s, "[evaluate.mubeam.params.njobs]",
                           "a prodtools setting, not a param to map")

    def test_a_clean_study_has_no_problems(self):
        for doc in (BRANIN, PTG4BL, DEMO,
                    profile_doc(toy_step(params={"r": "prof"}))):
            with self.subTest(study=doc["name"]):
                self.assertEqual(kp.problems(self.load(doc)), [])


class TestBuild(_Case):
    def test_build_resolves_every_origin(self):
        s = self.load(profile_doc(
            toy_step("up"),
            dict(toy_step("toy", params={"r": "prof", "x1": "x1"},
                          params_from={"x2": "up.branin"}),
                 fixed={"delay_s": 0.5, "fail": "${ARTIFACT}/x"})))
        sender = kp.sender_of(s.steps[1])
        env = {"x1": 1.0, "prof": [0.1, 0.2, 0.3]}
        with mock.patch.multiple(paths, ARTIFACT_ROOT=Path("/art"),
                                 BACKING=None):
            got = kp.build(s, sender, env, {"up": {"metrics": {"branin": 7.0}}})
        self.assertEqual(list(got), list(kp.names(s, sender)))
        self.assertEqual(got, {"r_0": 0.1, "r_1": 0.2, "r_2": 0.3, "x1": 1.0,
                               "x2": 7.0, "function": "branin_currin",
                               "delay_s": 0.5, "fail": "/art/x"})

    def test_build_keeps_todays_params_from_refusals(self):
        s = self.load(profile_doc(toy_step("up"), toy_step(
            "toy", params_from={"x2": "up.branin"})))
        sender = kp.sender_of(s.steps[1])
        for metrics, needle in (({}, "returned no metric 'branin'"),
                                ({"branin": float("nan")},
                                 "not a finite number"),
                                ({"branin": "7"}, "not a finite number")):
            with self.subTest(metrics=metrics):
                with self.assertRaises(ValueError) as cm:
                    kp.build(s, sender, {}, {"up": {"metrics": metrics}})
                self.assertIn(needle, str(cm.exception))

    def test_build_refuses_a_name_with_two_origins(self):
        s = self.load(profile_doc(toy_step(params={"r": "prof",
                                                   "r_1": "x1"})))
        with self.assertRaises(ValueError) as cm:
            kp.build(s, kp.sender_of(s.steps[0]),
                     {"x1": 1.0, "prof": [0.1, 0.2, 0.3]}, {})
        self.assertIn("exactly one source", str(cm.exception))


class TestNestedPaths(unittest.TestCase):
    def test_refuse_nested_paths(self):
        with self.assertRaises(ValueError) as cm:
            kp.refuse_nested_paths({"f": "${ARTIFACT}/a"}, "x[deck_params]")
        self.assertIn("[deck_params][f]", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            kp.refuse_nested_paths(
                ["ok", "/exp/mu2e/app/users/someone/x"],  # personal-path-ok: a refused value under test
                "x[pdg]")
        self.assertIn("[pdg][1]", str(cm.exception))
        for value in ([13, -211], ["GeomSolids1001"], "${ARTIFACT}/a"):
            with self.subTest(value=value):
                kp.refuse_nested_paths(value, "x")


if __name__ == "__main__":
    unittest.main()
