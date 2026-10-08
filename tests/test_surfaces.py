"""Тесты поверхностей: фон слоя, контраст текста, компоненты на необычном фоне."""

import tempfile
import unittest
from pathlib import Path

from coloro import db as dbm
from coloro import search, surfaces, tokens
from coloro.filters import Filter
from coloro.load import load_file
from coloro.walk import surface_of

from test_foundation import FakeFigma, node, page, solid
from test_search import FakeWithComponents, text

WHITE, BLACK, GREY = solid(1, 1, 1), solid(0, 0, 0), solid(0.8, 0.8, 0.8)


def box(x, y, w, h):
    return {"absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h}}


class Surface(unittest.TestCase):
    def test_translucent_fill_blends_with_what_is_under(self):
        s = surface_of({"type": "FRAME", "fills": [solid(0, 0, 0, 0.5)]}, ("solid", "FFFFFF", 100, None), {})
        self.assertEqual(s[:3], ("solid", "808080", 100))
        self.assertIsNone(surface_of({"type": "TEXT", "fills": [BLACK]}, None, {}))      # буквы — не фон
        self.assertEqual(surface_of({"type": "FRAME", "fills": [{"type": "IMAGE"}]}, None, {})[0], "image")

    def test_contrast(self):
        self.assertEqual(surfaces.ratio("000000", "FFFFFF"), 21.0)
        self.assertLess(surfaces.ratio("CCCCCC", "FFFFFF"), 3)


class Report(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = dbm.connect(Path(self.tmp.name) / "t.sqlite")
        kids = [
            text("ok", "Читается", fills=[BLACK], **box(10, 10, 50, 10)),
            text("bad", "Не читается", fills=[GREY], **box(10, 30, 50, 10)),
            # Белые буквы с тёмной обводкой на белом читаются.
            text("outlined", "999", fills=[WHITE], strokes=[BLACK], strokeWeight=2, **box(10, 50, 50, 10)),
            text("emoji", "🇷🇺", fills=[WHITE], **box(10, 70, 50, 10)),
            # Белая плашка закрывает надпись наполовину: фон смешанный, проверить глазами.
            node("half", fills=[BLACK], **box(0, 300, 30, 10)),
            text("edge", "На краю", fills=[WHITE], **box(10, 300, 40, 10)),
            # Подложка-сосед: тёмный прямоугольник, поверх него белый текст.
            node("plate", fills=[BLACK], **box(0, 100, 200, 50)),
            text("on_plate", "На подложке", fills=[WHITE], **box(10, 110, 50, 10)),
            node("pic", "FRAME", fills=[{"type": "IMAGE", "imageRef": "x"}], **box(0, 200, 200, 50),
                 children=[text("on_pic", "На картинке", fills=[WHITE], **box(10, 210, 50, 10))]),
        ]
        # Кнопка: десять раз на белом, один раз на тёмной подложке — необычное место.
        kids += [node(f"b{i}", "INSTANCE", "Кнопка", componentId="C1", **box(300, 20 * i, 10, 10)) for i in range(10)]
        kids += [node("dark", "FRAME", fills=[BLACK], **box(500, 0, 100, 100),
                      children=[node("b_dark", "INSTANCE", "Кнопка", componentId="C1", **box(510, 10, 10, 10))])]
        f = FakeWithComponents([page("1:1", "Stage", [node("s", "FRAME", "Экран", fills=[WHITE], children=kids,
                                                           **box(0, 0, 1000, 1000))])])
        load_file(self.con, f, "K")
        self.d = surfaces.report(self.con, Filter(), tokens.load(self.con))

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_contrast_by_surface(self):
        by = {(i["surface"], i["color"]): i for i in self.d["contrast"] if not i["outline"]}
        self.assertEqual(by[("#FFFFFF", "000000")]["status"], "aaa")
        self.assertEqual(by[("#FFFFFF", "CCCCCC")]["status"], "fail")
        self.assertEqual(by[("#000000", "FFFFFF")]["status"], "aaa")     # подложка-сосед найдена
        self.assertEqual(by[("Image", "FFFFFF")]["status"], "unknown")
        self.assertEqual(self.d["totals"]["fail"], 1)
        outlined = next(i for i in self.d["contrast"] if i["outline"])
        self.assertEqual((outlined["status"], outlined["fg"]), ("aaa", "FFFFFF@100~000000"))
        self.assertEqual(self.d["totals"]["texts"], 6)            # эмодзи не проверяются
        self.assertEqual(by[("Partly on a plate", "FFFFFF")]["status"], "unknown")

    def test_unusual_component_placement(self):
        g = next(c for c in self.d["components"] if c["name"] == "Кнопка")
        self.assertEqual(g["tones"], {"light": 10, "dark": 1})
        self.assertEqual([(u["tone"], u["uses"]) for u in g["unusual"]], [("dark", 1)])
        cond, args, _ = search.condition("surface", {"what": "component", "set": "Кнопка",
                                                     "bgs": ",".join(map(str, g["unusual"][0]["bgs"]))}, self.con)
        ids = [i["node_id"] for i in search.layers(self.con, Filter(), cond, args, "K", "s")["items"]]
        self.assertEqual(ids, ["b_dark"])

    def test_places_of_a_text_pair(self):
        bad = next(i for i in self.d["contrast"] if i["status"] == "fail")
        cond, args, _ = search.condition("surface", {"what": "text", "bg": str(bad["bg"]), "color": bad["color"],
                                                     "alpha": str(bad["alpha"])}, self.con)
        ids = [i["node_id"] for i in search.layers(self.con, Filter(), cond, args, "K", "s")["items"]]
        self.assertEqual(ids, ["bad"])


if __name__ == "__main__":
    unittest.main()
