"""Тесты: поиск всем сразу, фильтры по найденному, градиенты, токены, проекты."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from coloro import db as dbm
from coloro import health, inventory, search, server, tokens
from coloro.filters import Filter
from coloro.load import load_file

from test_foundation import FakeFigma, node, page, solid
from test_search import FakeWithComponents, text

PINK = solid(1, 0, 111 / 255)


def grad(*stops):
    return {"type": "GRADIENT_LINEAR", "gradientStops": [
        {"position": i, "color": {"r": r, "g": g, "b": b, "a": 1}} for i, (r, g, b) in enumerate(stops)]}


class Find(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = dbm.connect(Path(self.tmp.name) / "t.sqlite")
        box = {"x": 0, "y": 0, "width": 56, "height": 56}
        f = FakeWithComponents([
            page("1:1", "Stage 1", [node("s1", "FRAME", "Магазин", children=[
                text("t1", "Купить 100 монет", fills=[PINK]),
                text("t2", "Купить подписку"),
                node("b1", "INSTANCE", "Кнопка", componentId="C1", absoluteBoundingBox=box, fills=[PINK]),
                node("b2", "INSTANCE", "Кнопка", componentId="C2", absoluteBoundingBox=box),
                node("r1", fills=[grad((1, 0, 0), (0, 0, 1))]),
                node("r2", fills=[grad((1, 0, 0), (0, 0, 1))]),
            ])]),
            page("2:2", "Stage 2", [node("s2", "FRAME", "Профиль", children=[
                node("b3", "INSTANCE", "Avatar", componentId="C3", absoluteBoundingBox=box),
            ])]),
        ])
        load_file(self.con, f, "K")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def found(self, **q):
        res = search.find(self.con, Filter(), {k: v if isinstance(v, list) else [v] for k, v in q.items()})
        ids = set()
        for g in res["items"]:
            cond, args, _ = search.build(self.con, {k: v if isinstance(v, list) else [v] for k, v in q.items()})
            ids |= {i["node_id"] for i in search.layers(self.con, Filter(), cond, args, g["file_key"], g["screen_id"])["items"]}
        return res, sorted(ids)

    def test_text_finds_component_instances_by_name(self):
        _, ids = self.found(q="кнопка")
        self.assertEqual(ids, ["b1", "b2"])

    def test_text_where_text_only(self):
        _, ids = self.found(q="купить", where="text")
        self.assertEqual(ids, ["t1", "t2"])

    def test_parts_combine_with_and(self):
        # Размер 56 × 56 и розовый цвет — только одна кнопка.
        _, ids = self.found(w="56", h="56", color="#FF006F")
        self.assertEqual(ids, ["b1"])

    def test_colour_without_alpha_ignores_opacity(self):
        _, ids = self.found(color="#FF0070", ctol="3")
        self.assertEqual(ids, ["b1", "t1"])

    def test_facets_count_the_found(self):
        res, _ = self.found(w="56", h="56")
        types = {f["value"]: f["count"] for f in res["facets"]["type"]}
        self.assertEqual(types, {"instance": 3})
        comps = {f["value"]: f["count"] for f in res["facets"]["comp"]}
        self.assertEqual(comps, {"Кнопка": 2, "Avatar": 1})
        self.assertEqual(res["facets"]["props"]["Size"], [{"value": "B", "count": 1}, {"value": "M", "count": 1}])
        pages = {f["value"]: f["count"] for f in res["facets"]["page"]}
        self.assertEqual(pages, {"Stage 1": 2, "Stage 2": 1})

    def test_facet_filters_narrow(self):
        _, ids = self.found(w="56", h="56", comp="Кнопка", prop_Size="B")
        self.assertEqual(ids, ["b1"])
        _, ids = self.found(w="56", h="56", page="Stage 2")
        self.assertEqual(ids, ["b3"])
        _, ids = self.found(q="купить", type="instance")
        self.assertEqual(ids, [])

    def test_exact_phrase_vs_word_forms(self):
        # «купить монет» в любой форме — находит; точная фраза «100 монет» — тоже;
        # точная фраза «монет купить» — нет: порядок слов важен.
        _, ids = self.found(q="монеты купить", where="text")
        self.assertEqual(ids, ["t1"])
        _, ids = self.found(q="100 монет", where="text", mode="exact")
        self.assertEqual(ids, ["t1"])
        _, ids = self.found(q="монет купить", where="text", mode="exact")
        self.assertEqual(ids, [])

    def test_whole_words_flag(self):
        # «подпис» частью слова есть в «подписку», целым словом «подпись» — нет.
        _, ids = self.found(q="подпис", where="text", mode="exact")
        self.assertEqual(ids, ["t2"])
        _, ids = self.found(q="подпис", where="text", mode="exact", whole="1")
        self.assertEqual(ids, [])
        _, ids = self.found(q="монеты", where="text", whole="1")
        self.assertEqual(ids, ["t1"])
        self.assertEqual(search.texts(self.con, Filter(), "монет", mode="exact", whole=True)["matched"], 1)

    def test_several_places_at_once(self):
        _, ids = self.found(q="кнопка", where=["name"])
        self.assertEqual(ids, ["b1", "b2"])       # слои с этим названием
        _, ids = self.found(q="купить", where=["text", "component"])
        self.assertEqual(ids, ["t1", "t2"])

    def test_texts_inventory(self):
        d = search.texts(self.con, Filter())
        by = {i["key"]: i for i in d["items"]}
        self.assertEqual(by["купить подписку"]["uses"], 1)
        self.assertEqual(search.texts(self.con, Filter(), "монеты")["total"], 1)
        cond, args, _ = search.condition("textexact", {"text": "Купить 100 монет"})
        ids = [i["node_id"] for i in search.layers(self.con, Filter(), cond, args, "K", "s1")["items"]]
        self.assertEqual(ids, ["t1"])

    def test_empty_query_is_an_error(self):
        with self.assertRaises(search.SearchError):
            search.build(self.con, {})

    def test_layer_details(self):
        cond, args, _ = search.build(self.con, {"q": ["монет"]})
        item = search.layers(self.con, Filter(), cond, args, "K", "s1")["items"][0]
        self.assertEqual(item["paints"][0]["color"], "FF006F")
        self.assertEqual(item["paints"][0]["source"], "manual")

    def test_gradient_recipes(self):
        g = inventory.gradients(self.con, Filter())
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["kind"], g[0]["uses"], [s["color"] for s in g[0]["stops"]]), ("linear", 2, ["FF0000", "0000FF"]))
        cond, args, _ = search.condition("gradient", {"grad": g[0]["id"]})
        ids = [i["node_id"] for i in search.layers(self.con, Filter(), cond, args, "K", "s1")["items"]]
        self.assertEqual(sorted(ids), ["r1", "r2"])

    def test_token_usage_shows_unused(self):
        idx = tokens.Index(tokens.parse("name,value\nbrand/pink,#FF006F\nbrand/unused,#123456\n"))
        usage = {t["name"]: t for t in tokens.usage(idx, inventory.colours(self.con, Filter(), idx))}
        self.assertEqual(usage["brand/pink"]["uses"], 2)
        self.assertEqual(usage["brand/unused"]["uses"], 0)


class Inspect(unittest.TestCase):
    def test_layers_relative_to_render_bounds(self):
        from coloro import inspect
        entry = {"styles": {"S:1": {"name": "Brand/Pink"}}, "document": {
            "id": "1:1", "type": "COMPONENT", "name": "Button",
            "absoluteBoundingBox": {"x": 100, "y": 200, "width": 120, "height": 40},
            "absoluteRenderBounds": {"x": 96, "y": 198, "width": 128, "height": 48},
            "layoutMode": "HORIZONTAL", "itemSpacing": 8, "paddingTop": 12, "paddingRight": 16, "paddingBottom": 12, "paddingLeft": 16,
            "layoutSizingHorizontal": "HUG", "layoutSizingVertical": "FIXED", "cornerRadius": 8,
            "boundVariables": {"paddingLeft": {"id": "v"}},
            "fills": [{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 111 / 255, "a": 1}}], "styles": {"fill": "S:1"},
            "children": [{"id": "1:2", "type": "TEXT", "name": "Label", "characters": "Buy",
                          "absoluteBoundingBox": {"x": 116, "y": 212, "width": 30, "height": 16},
                          "style": {"fontFamily": "Inter", "fontStyle": "Medium", "fontWeight": 500, "fontSize": 13, "lineHeightPx": 16}},
                         {"id": "1:3", "type": "VECTOR", "name": "hidden", "visible": False,
                          "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1, "height": 1}}]}}
        idx = tokens.Index(tokens.parse("name,value\nbrand/pink,#FF006F\n"))
        d = inspect.build(entry, idx)
        self.assertEqual((d["width"], d["height"]), (128, 48))
        root, label = d["layers"]
        self.assertEqual((root["x"], root["y"]), (4, 2))          # рамка слоя — от границ отрисовки
        self.assertEqual(root["layout"], {"dir": "row", "gap": 8, "pad": [12, 16, 12, 16], "main": "start", "cross": "start", "wrap": False})
        self.assertEqual(root["sizing"], ["hug", "fixed"])
        self.assertEqual(root["bound"], ["paddingLeft"])
        self.assertEqual(root["fills"][0]["tokens"], ["brand/pink"])
        self.assertEqual(root["fills"][0]["style"], "Brand/Pink")
        self.assertEqual((label["p"], label["x"], label["text"]["size"]), (0, 20, 13))
        self.assertEqual(len(d["layers"]), 2)                   # скрытый слой не показывается


class Projects(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.sqlite"
        self.con = dbm.connect(self.path)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_projects_do_not_mix(self):
        a = server.create_project(self.con, "App")["id"]
        b = server.create_project(self.con, "Site")["id"]
        server.add_source(self.con, "https://www.figma.com/design/KA/x", None, a)
        server.add_source(self.con, "https://www.figma.com/design/KB/x", None, b)
        for key, colour in (("KA", (1, 0, 0)), ("KB", (0, 0, 1))):
            load_file(self.con, FakeFigma([page("1:1", "Stage", [node("s", "FRAME", children=[node("r", fills=[solid(*colour)])])])]), key)
        only_a = {i["color"] for i in inventory.colours(self.con, Filter(project=a), tokens.Index([]))}
        self.assertEqual(only_a, {"FF0000"})
        o = health.overview(self.con, Filter(project=b), tokens.Index([]))
        self.assertEqual([f["file_key"] for f in o["files"]], ["KB"])

    def test_same_link_in_two_projects_keeps_data_until_last(self):
        a = server.create_project(self.con, "App")["id"]
        b = server.create_project(self.con, "Site")["id"]
        url = "https://www.figma.com/design/KA/x"
        server.add_source(self.con, url, None, a)
        server.add_source(self.con, url, None, b)
        load_file(self.con, FakeFigma([page("1:1", "Stage", [node("s", "FRAME")])]), "KA")
        server.remove_project(self.con, a)
        self.assertTrue(self.con.execute("SELECT 1 FROM nodes WHERE file_key = 'KA'").fetchone())
        server.remove_project(self.con, b)
        self.assertIsNone(self.con.execute("SELECT 1 FROM nodes WHERE file_key = 'KA'").fetchone())

    def test_token_library_per_project(self):
        a = server.create_project(self.con, "App")["id"]
        b = server.create_project(self.con, "Site")["id"]
        tokens.store(self.con, tokens.parse("name,value\nred,#FF0000\n"), "a.csv", a)
        self.assertEqual(len(tokens.load(self.con, a).items), 1)
        self.assertEqual(len(tokens.load(self.con, b).items), 0)

    def test_history_per_project(self):
        a = server.create_project(self.con, "App")["id"]
        server.add_source(self.con, "https://www.figma.com/design/KA/x", None, a)
        load_file(self.con, FakeFigma([page("1:1", "Stage", [node("s", "FRAME", children=[node("r", fills=[solid(1, 0, 0)])])])]), "KA")
        self.assertIsNotNone(health.snapshot(self.con, tokens.Index([]), a))
        self.assertEqual(len(health.history(self.con, a)), 1)
        self.assertEqual(health.history(self.con, None), [])

    def test_old_base_becomes_one_project(self):
        # База до проектов: ссылка уникальна на всю базу, у ссылок и токенов нет проекта.
        old = Path(self.tmp.name) / "old.sqlite"
        raw = sqlite3.connect(old)
        raw.executescript("""
            CREATE TABLE sources (id INTEGER PRIMARY KEY, url TEXT UNIQUE, file_key TEXT, node_id TEXT, pages TEXT, added_at TEXT);
            INSERT INTO sources (url, file_key) VALUES ('https://www.figma.com/design/KA/x', 'KA');
            CREATE TABLE tokens (name TEXT, color TEXT, alpha INTEGER, mode TEXT, collection TEXT);
            INSERT INTO tokens VALUES ('red', 'FF0000', 100, NULL, NULL);
            CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID;
            INSERT INTO meta VALUES ('tokens_file', 'kit.csv');""")
        raw.commit()
        raw.close()
        con = dbm.connect(old)
        try:
            projects = con.execute("SELECT id, name, tokens_file FROM projects").fetchall()
            self.assertEqual(len(projects), 1)
            pid = projects[0][0]
            self.assertEqual(projects[0][2], "kit.csv")
            self.assertEqual(con.execute("SELECT project_id FROM sources").fetchone()[0], pid)
            self.assertEqual(len(tokens.load(con, pid).items), 1)
            # Теперь ту же ссылку можно добавить во второй проект.
            b = server.create_project(con, "Site")["id"]
            server.add_source(con, "https://www.figma.com/design/KA/x", None, b)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 2)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
