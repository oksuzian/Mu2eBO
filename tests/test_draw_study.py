"""graph/draw_study.py: every installed study draws, with one node per
step and an edge for each files_from and params_from."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph"))
import draw_study  # noqa: E402

STUDIES = sorted((ROOT / "mode_specs").glob("*.json"))


class TestDrawStudy(unittest.TestCase):
    def test_every_study_has_its_steps_and_edges(self):
        for path in STUDIES:
            doc = json.loads(path.read_text())
            dot = draw_study.study_dot(doc)
            for s in doc["evaluate"]:
                self.assertIn(f'"step:{s["step"]}" [label=', dot, path.name)
                for up in s["files_from"]:
                    self.assertIn(f'"step:{up}" -> "step:{s["step"]}"', dot)
                for src in s["params_from"].values():
                    up = src.split(".", 1)[0]
                    self.assertIn(f'"step:{up}" -> "step:{s["step"]}"', dot)
            for o in doc["objectives"]:
                self.assertIn(f'"obj:{o["name"]}"', dot, path.name)

    def test_a_name_resolves_to_its_file(self):
        self.assertEqual(draw_study.resolve_target("ce_chain"),
                         ROOT / "mode_specs" / "ce_chain.json")
        with self.assertRaises(ValueError):
            draw_study.resolve_target("no_such_study")

    @unittest.skipIf(shutil.which("dot") is None, "Graphviz dot not on PATH")
    def test_it_writes_a_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ce_chain.pdf"
            self.assertEqual(draw_study.main(["ce_chain", "-o", str(out)]), 0)
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))

    @unittest.skipIf(shutil.which("dot") is None, "Graphviz dot not on PATH")
    def test_it_writes_a_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ce_chain.png"
            self.assertEqual(draw_study.main(["ce_chain", "-o", str(out)]), 0)
            self.assertTrue(out.read_bytes().startswith(b"\x89PNG"))
            out2 = Path(tmp) / "picture"
            self.assertEqual(draw_study.main(
                ["ce_chain", "-o", str(out2), "--format", "png"]), 0)
            self.assertTrue(out2.read_bytes().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
