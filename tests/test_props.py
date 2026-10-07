"""Тесты: отступы, скругления, обводки, эффекты, картинки — и что загрузка не держит базу."""

import tempfile
import threading
import unittest
from pathlib import Path

from coloro import db as dbm
from coloro import effects, scales, search
from coloro.filters import Filter
from coloro.load import load_file

from test_foundation import FakeFigma, node, page


def auto(nid, **kw):
    base = {"layoutMode": "HORIZONTAL", "itemSpacing": 12, "paddingTop": 16, "paddingRight": 16,
            "paddingBottom": 16, "paddingLeft": 0}
    base.update(kw)
    return node(nid, "FRAME", **base)


BIG = {"x": 0, "y": 0, "width": 100, "height": 100}
SHADOW = {"type": "DROP_SHADOW", "visible": True, "color": {"r": 0, "g": 0, "b": 0, "a": 0.25},
          "offset": {"x": 0, "y": 4}, "radius": 8, "spread": 0}


class Extract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = dbm.connect(Path(self.tmp.name) / "t.sqlite")
        f = FakeFigma([page("1:1", "Stage", [node("s1", "FRAME", "Экран", children=[
            auto("a1", boundVariables={"paddingTop": {"id": "v"}}),
            auto("a2", primaryAxisAlignItems="SPACE_BETWEEN"),
            node("r1", cornerRadius=8, absoluteBoundingBox=BIG),
            node("r2", cornerRadius=8, rectangleCornerRadii=[8, 8, 0, 0], absoluteBoundingBox=BIG),
            node("r3", cornerRadius=7, absoluteBoundingBox=BIG),
            node("p1", cornerRadius=5),                       # 10 × 10, скругление 5 — «таблетка»
            auto("a3", itemSpacing=15.5),
            node("e3", effects=[dict(SHADOW, offset={"x": 0, "y": 5})]),
            node("e4", effects=[dict(SHADOW, type="INNER_SHADOW")]),
            node("in", "INSTANCE", effects=[SHADOW], cornerRadius=3, absoluteBoundingBox=BIG),
            node("k1", strokes=[{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}], strokeWeight=1),
            node("k2", strokes=[{"type": "SOLID", "visible": False, "color": {"r": 0, "g": 0, "b": 0}}], strokeWeight=3),
            node("e1", effects=[SHADOW, dict(SHADOW, visible=False)]),
            node("e2", effects=[SHADOW], styles={"effect": "S:1"}),
            node("i1", fills=[{"type": "IMAGE", "imageRef": "abc", "scaleMode": "FILL"}]),
        ])])])
        f.styles = {"S:1": {"name": "Shadow/Card", "styleType": "EFFECT"}}
        load_file(self.con, f, "K")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def rows(self, sql):
        return sorted(self.con.execute(sql).fetchall())

    def test_spacing(self):
        got = self.rows("SELECT node_id, kind, value, bound FROM props WHERE kind IN ('gap', 'padding') AND node_id IN ('a1', 'a2')")
        self.assertEqual(got, sorted([
            ("a1", "gap", 12.0, 0), ("a1", "padding", 16.0, 1), ("a1", "padding", 16.0, 0), ("a1", "padding", 16.0, 0),
            # «Space between»: записанный промежуток не применяется — не считаем; нули не пишем.
            ("a2", "padding", 16.0, 0), ("a2", "padding", 16.0, 0), ("a2", "padding", 16.0, 0)]))

    def test_radius_and_stroke(self):
        self.assertEqual(self.rows("SELECT node_id, value FROM props WHERE kind = 'radius' AND node_id LIKE 'r%'"),
                         [("r1", 8.0), ("r2", 8.0), ("r2", 8.0), ("r3", 7.0)])
        # Скрытая обводка толщины не имеет.
        self.assertEqual(self.rows("SELECT node_id, value FROM props WHERE kind = 'stroke'"), [("k1", 1.0)])

    def test_effects(self):
        got = self.rows("SELECT node_id, type, color, alpha, y, radius, src FROM effects WHERE node_id IN ('e1', 'e2')")
        self.assertEqual(got, [("e1", "DROP_SHADOW", "000000", 25, 4.0, 8.0, None),
                               ("e2", "DROP_SHADOW", "000000", 25, 4.0, 8.0, "s:Shadow/Card")])

    def test_images(self):
        self.assertEqual(self.rows("SELECT node_id, ref, mode FROM images"), [("i1", "abc", "FILL")])


    # --- анализ

    def found(self, kind, **q):
        cond, args, _ = search.condition(kind, q, self.con)
        return sorted(i["node_id"] for i in search.layers(self.con, Filter(), cond, args, "K", "s1")["items"])

    def test_spacing_scale_from_variables(self):
        sp = scales.report(self.con, Filter())["spacing"]
        self.assertEqual(sp["source"], "variables")
        self.assertEqual([v["value"] for v in sp["scale"]], [16.0])
        st = {i["value"]: i["status"] for i in sp["items"]}
        # 16 есть в шкале, но набрано вручную; 15,5 — в пределах пикселя; 12 — мимо.
        self.assertEqual(st, {16.0: "unbound", 15.5: "near", 12.0: "off"})
        self.assertEqual(self.found("prop", group="spacing", value="12"), ["a1"])
        self.assertEqual(self.found("prop", group="spacing", value="15.5"), ["a3"])

    def test_radius_grid_fallback_and_pill(self):
        r = scales.report(self.con, Filter())["radius"]
        self.assertEqual(r["source"], "grid")
        st = {i["value"]: i["status"] for i in r["items"]}
        self.assertEqual(st, {8.0: "ok", 7.0: "near"})
        self.assertEqual(r["totals"]["pill"], 1)
        # Инстанс не считается: его скругление задаёт компонент.
        self.assertNotIn(3.0, st)
        self.assertEqual(self.found("prop", group="radius", value="7"), ["r3"])

    def test_effect_statuses(self):
        d = effects.report(self.con, Filter())
        self.assertEqual(d["totals"]["styled"], 1)
        st = {(i["type"], i["y"]): i["status"] for i in d["items"]}
        self.assertEqual(st, {("DROP_SHADOW", 4.0): "unbound", ("DROP_SHADOW", 5.0): "near", ("INNER_SHADOW", 4.0): "off"})
        e = next(i for i in d["items"] if i["status"] == "unbound")
        self.assertEqual(e["styles"], ["Shadow/Card"])
        q = {k: e[k] for k in ("type", "color", "alpha", "x", "y", "radius", "spread")}
        self.assertEqual(self.found("effect", **q), ["e1"])

    def test_images_report(self):
        d = effects.images(self.con, Filter())
        self.assertEqual((d["total"], d["total_uses"], d["once"]), (1, 1, 1))
        self.assertEqual(self.found("image", ref="abc"), ["i1"])


class NoLockDuringDownload(unittest.TestCase):
    """Пока страница качается, база свободна: иначе параллельные загрузки упираются в блокировку."""

    def test_no_open_transaction_while_fetching(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = dbm.connect(Path(tmp) / "t.sqlite")
            seen = []

            class Watch(FakeFigma):
                def nodes(self, key, ids, depth=None):
                    seen.append(con.in_transaction)
                    return super().nodes(key, ids, depth)

            sect = node("sec", "SECTION", "Раздел", children=[
                node("t1", "TEXT", "Текст", characters="Привет",
                     style={"fontFamily": "Inter", "fontWeight": 400, "fontSize": 14}),
                node("g1", fills=[{"type": "GRADIENT_LINEAR", "gradientStops": [
                    {"position": 0, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
                    {"position": 1, "color": {"r": 0, "g": 0, "b": 1, "a": 1}}]}]),
            ])
            # Больше восьми верхних слоёв — значит, несколько запросов, и часть идёт после того,
            # как словарь уже пополнялся.
            tops = [sect] + [node(f"f{i}", "FRAME") for i in range(12)]
            load_file(con, Watch([page("1:1", "Stage", tops)]), "K")
            con.close()
            self.assertTrue(seen)
            self.assertFalse(any(seen))


class ConnectWhileWriting(unittest.TestCase):
    """Новое соединение открывается, пока другой поток держит запись: не ждёт и не падает."""

    def test_connect_during_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.sqlite"
            writer = dbm.connect(path)
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO vals (v) VALUES ('x')")
            result = []

            def other():
                try:
                    dbm.connect(path).close()
                    result.append("ok")
                except Exception as e:          # noqa: BLE001 — нужен сам факт ошибки
                    result.append(repr(e))
            t = threading.Thread(target=other)
            t.start()
            t.join(timeout=5)
            writer.rollback()
            writer.close()
            t.join()
            self.assertEqual(result, ["ok"])


if __name__ == "__main__":
    unittest.main()
