"""Тесты второго этапа: цвет, справочник токенов, фильтры, левые цвета, общая картина."""

import tempfile
import unittest
from pathlib import Path

from coloro import color as colorm
from coloro import db as dbm
from coloro import health, inventory, tokens
from coloro.filters import Filter
from coloro.load import load_file

from test_foundation import FakeFigma, node, page, solid


class Colour(unittest.TestCase):
    # Эталонные пары из статьи, где CIEDE2000 и проверяют (Sharma, Wu, Dalal, 2005).
    PAIRS = [((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
             ((50, 2.49, -0.001), (50, -2.49, 0.0011), 7.2195),   # переход оттенка через 180°
             ((50, 2.5, 0), (73, 25, -18), 27.1492),
             ((2.0776, 0.0795, -1.135), (0.9033, -0.0636, -0.5514), 0.9082)]

    def test_ciede2000_reference(self):
        for a, b, want in self.PAIRS:
            self.assertAlmostEqual(colorm.de2000(a, b), want, places=4)

    def test_parse(self):
        self.assertEqual(colorm.parse("#fff"), ("FFFFFF", 100))
        self.assertEqual(colorm.parse("#00000026"), ("000000", 15))
        self.assertEqual(colorm.parse("rgba(255, 0, 111, 0.5)"), ("FF006F", 50))
        self.assertEqual(colorm.parse("rgb(255 0 111 / 40%)"), ("FF006F", 40))
        self.assertIsNone(colorm.parse("8px"))


class Tokens(unittest.TestCase):
    def test_same_value_two_names_not_merged(self):
        idx = tokens.Index(tokens.parse("name,value\nbg/white,#FFFFFF\ntext/inverse,#FFFFFF\n"))
        self.assertEqual(sorted(idx.exact("FFFFFF", 100)), ["bg/white", "text/inverse"])

    def test_w3c_with_references(self):
        rows = tokens.parse('{"c":{"$type":"color","a":{"$value":"#FF006F"},"b":{"$value":"{c.a}"},'
                            '"s":{"$value":"8px","$type":"dimension"}}}')
        self.assertEqual({r[0] for r in rows}, {"c/a", "c/b"})

    def test_legacy_russian_csv(self):
        text = ("Ключ;Имя;Коллекция;Тип;Главное значение;Второе значение;Тип значений\n"
                "k;Shapes/B2;K;COLOR;#FFFFFF;#2F313C;режим темы\n"
                "k;Radius/M;K;FLOAT;12;;константа\n")
        rows = tokens.parse(text)
        self.assertEqual([(r[0], r[1], r[3]) for r in rows], [("Shapes/B2", "FFFFFF", "1"), ("Shapes/B2", "2F313C", "2")])

    def test_nearest_reports_alpha_separately(self):
        idx = tokens.Index(tokens.parse("name,value\nblack,#000000\n"))
        name, c, a, de, da = idx.nearest("000000", 15)
        self.assertEqual((name, de, da), ("black", 0.0, 85))


class Stray(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = dbm.connect(Path(self.tmp.name) / "t.sqlite")
        bound = {"boundVariables": {"color": {"id": "V"}}}
        f = FakeFigma([
            page("1:1", "Stage 1", [node("s1", "FRAME", "Экран", children=[
                node("a", fills=[solid(1, 0, 111 / 255, **bound)]),     # токен, привязан
                node("b", fills=[solid(1, 0, 111 / 255)]),              # значение токена, вручную
                node("c", fills=[solid(1, 0, 112 / 255)]),              # почти токен
                node("d", fills=[solid(0, 0.5, 0)]),                    # мимо системы
                node("h", fills=[solid(0, 0.5, 0)], visible=False),     # скрытый
            ])]),
            page("2:2", "Old (archive)", [node("s2", "FRAME", children=[node("z", fills=[solid(0, 0, 1)])])]),
        ])
        load_file(self.con, f, "K")
        self.idx = tokens.Index(tokens.parse("name,value\nbrand/primary,#FF006F\n"))

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def by(self, items):
        return {i["color"]: i for i in items}

    def test_categories(self):
        items = self.by(inventory.colours(self.con, Filter(), self.idx))
        self.assertEqual(items["FF006F"]["status"], "token")
        self.assertTrue(items["FF006F"]["unbound"])          # одно из двух — вручную
        self.assertEqual(items["FF0070"]["status"], "near")
        self.assertEqual(items["FF0070"]["nearest"]["name"], "brand/primary")
        self.assertEqual(items["008000"]["status"], "off")

    def test_filters_switch_without_reload(self):
        default = self.by(inventory.colours(self.con, Filter(), self.idx))
        self.assertEqual(default["008000"]["uses"], 1)           # скрытый не считается
        self.assertNotIn("0000FF", default)                       # архив не считается
        everything = self.by(inventory.colours(self.con, Filter(hidden=True, archive=True), self.idx))
        self.assertEqual(everything["008000"]["uses"], 2)
        self.assertIn("0000FF", everything)

    def test_places_link_to_layer(self):
        got = inventory.places(self.con, Filter(), "FF0070", 100)
        self.assertEqual(got["total"], 1)
        p = got["items"][0]
        self.assertEqual((p["file"], p["page"], p["screen"], p["name"]), ("File", "Stage 1", "Экран", "c"))
        self.assertTrue(p["link"].startswith("https://www.figma.com/design/K/?node-id="))

    def test_link_inside_instance_goes_to_instance(self):
        self.assertEqual(inventory.figma_link("K", "12:34"), "https://www.figma.com/design/K/?node-id=12-34")

    def test_overview(self):
        o = health.overview(self.con, Filter(), self.idx)
        m = o["totals"]
        self.assertEqual((m["near"], m["off"], m["unbound"]), (1, 1, 1))
        self.assertEqual(m["uses"], 4)
        self.assertEqual(m["raw"], 3)
        self.assertEqual(o["files"][0]["metrics"]["levels"]["raw_pct"], "bad")

    def test_without_tokens_stray_is_unknown_not_zero(self):
        o = health.overview(self.con, Filter(), tokens.Index([]))
        self.assertIsNone(o["totals"]["stray"])

    def test_trend_from_snapshots(self):
        health.snapshot(self.con, self.idx)
        self.assertIsNone(health.overview(self.con, Filter(), self.idx)["trend"])
        import time; time.sleep(1.1)
        health.snapshot(self.con, self.idx)
        self.assertIsNotNone(health.overview(self.con, Filter(), self.idx)["trend"])


if __name__ == "__main__":
    unittest.main()


class Categories(unittest.TestCase):
    """Порядок категорий: почти токен с учётом прозрачности важнее «другой прозрачности»."""

    def setUp(self):
        self.idx = tokens.Index(tokens.parse("name,value\nwhite,#FFFFFF\nwhite/40,#FFFFFF66\nbrand,#FF006F\n"))

    def status(self, c, a):
        return inventory.classify(c, a, self.idx)["status"]

    def test_same_alpha_near_is_near(self):
        self.assertEqual(self.status("FF0070", 100), "near")

    def test_other_alpha_same_colour(self):
        self.assertEqual(self.status("FFFFFF", 65), "alpha")

    def test_close_alpha_to_existing_token_is_near(self):
        # Есть токен белого 40% — белый 42% это почти он, а не «другая прозрачность».
        self.assertEqual(self.status("FFFFFF", 42), "near")

    def test_exact(self):
        self.assertEqual(self.status("FFFFFF", 40), "token")

    def test_far(self):
        self.assertEqual(self.status("00AA00", 100), "off")
