"""The params every live call sends, pinned on the code before core/kit_params.py.

For each live study and engine fixture: each step's params at the centre of
the knob box (every params_from metric read as 1.25e-3), and the preflight's,
as canonical JSON in tests/fixtures/golden_kit_params.json. The fixture was
written once, on ed39d1b, and is never regenerated: a diff means a call now
sends something else, which prodtools and beamkit would refuse on a resumed
point. `python -m tests.test_kit_params_golden --write` wrote it.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import paths  # noqa: E402
import scheduler  # noqa: E402
import study as st  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden_kit_params.json"
STUDIES = {p.stem: p for p in (
    [ROOT / "mode_specs" / f"{n}.json" for n in (
        "ce_chain", "foilsflash_ax", "foilspfbpz_ax", "ptg4bl",
        "foilspf_nominal")]
    + [ROOT / "tests" / "fixtures" / "engine_studies" / f"{n}.json"
       for n in ("branin", "foilspfbpz_local", "prodtools_smoke")])}
METRIC = 1.25e-3


def same_paths():
    """The artifact roots every machine shares, so an expanded
    '${ARTIFACT}/' value is the same string everywhere."""
    return mock.patch.multiple(
        paths, ARTIFACT_ROOT=Path("/nonexistent-artifact-root"), BACKING=None)


def centre(study):
    return [float((k.min + k.max) // 2) if k.type == "int"
            else (k.min + k.max) / 2 for k in study.knobs]


def sent(study):
    """{step name: its params, "<preflight>": the preflight's} at the box
    centre. Call it inside same_paths()."""
    x = centre(study)
    env = (study.geom.derived_env(x) if study.geom is not None
           else dict(zip(study.knob_names, x)))
    out = {}
    for step in study.steps:
        upstream = {up: {"metrics": {}} for up in step.upstream}
        for source in step.params_from.values():
            up, key = source.split(".", 1)
            upstream[up]["metrics"][key] = METRIC
        out[step.step] = scheduler.step_params(study, step, env, False,
                                               upstream)
    pre = study.preflight
    if pre is not None:
        out["<preflight>"] = scheduler.merge_params(
            "preflight", scheduler.map_params(pre["params"], env, False),
            study.kits.get(pre["kit"], {}))
    return out


def canonical(obj):
    return json.loads(json.dumps(obj, sort_keys=True, default=str))


def current():
    with same_paths():
        return {name: canonical(sent(st.load_study_file(path)))
                for name, path in STUDIES.items()}


class TestGolden(unittest.TestCase):
    maxDiff = None

    def test_every_call_sends_what_it_sent_at_ed39d1b(self):
        golden = json.loads(GOLDEN.read_text())
        self.assertEqual(sorted(golden), sorted(STUDIES))
        now = current()
        for name in STUDIES:
            with self.subTest(study=name):
                self.assertEqual(now[name], golden[name])


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        GOLDEN.write_text(json.dumps(current(), indent=1, sort_keys=True)
                          + "\n")
        print(f"wrote {GOLDEN}")
    else:
        unittest.main()
