"""Тест демо-проекта: собирается без Figma, и каждому разделу есть что показать."""

import tempfile
import unittest
from pathlib import Path

from coloro import comments, demo, health, surfaces, tokens
from coloro import db as dbm
from coloro.filters import Filter


class Demo(unittest.TestCase):
    def test_builds_with_findings_everywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = demo.build(Path(tmp) / "demo.sqlite")
            con = dbm.connect(path)
            try:
                f, idx = Filter(project=1), tokens.load(con, 1)
                t = health.overview(con, f, idx)["totals"]
                self.assertGreater(t["near"], 0)
                self.assertGreater(t["unbound"], 0)
                self.assertEqual(len(health.history(con, 1)), 3)            # три замера для графика
                s = surfaces.report(con, f, idx)["totals"]
                self.assertGreater(s["fail"], 0)
                self.assertGreater(s["unusual"], 0)
                self.assertGreater(comments.report(con, f)["totals"]["open"], 0)
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
