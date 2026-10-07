"""Тесты типографики: система стилей из макетов и сравнение текстов без стиля с ней."""

import tempfile
import unittest
from pathlib import Path

from coloro import db as dbm, typography
from coloro.filters import Filter
from coloro.load import load_file

from test_foundation import FakeFigma, node, page


def text(nid, family, weight, size, line, style_id=None, **kw):
    n = node(nid, "TEXT", nid, characters="Текст", style={
        "fontFamily": family, "fontWeight": weight, "fontSize": size, "lineHeightPx": line})
    if style_id:
        n["styles"] = {"text": style_id}
    n.update(kw)
    return n


class FakeStyles(FakeFigma):
    def nodes(self, key, ids, depth=None):
        res = super().nodes(key, ids, depth)
        for e in res["nodes"].values():
            e["styles"] = {"S1": {"name": "Body/M"}, "S2": {"name": "Title/L"}}
        return res


class Typography(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = dbm.connect(Path(self.tmp.name) / "t.sqlite")
        f = FakeStyles([page("1:1", "Stage", [node("s", "FRAME", "Экран", children=[
            text("a", "Ubuntu", 400, 16, 21, "S1"),             # стиль системы
            text("b", "Ubuntu", 700, 24, 24, "S2"),             # стиль системы
            text("c", "Ubuntu", 400, 16, 21),                   # как Body/M, но без стиля
            text("d", "Ubuntu", 700, 23.11, 23.11),             # масштабированный Title/L
            text("e", "Inter", 700, 20, 24),                    # чужой шрифт
            node("i", "INSTANCE", "Кнопка", children=[text("x", "Inter", 400, 13, 16)]),  # внутри компонента
        ])])])
        load_file(self.con, f, "K")
        self.r = typography.fonts(self.con, Filter())

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def by_label(self):
        return {i["label"]: i for i in self.r["items"]}

    def test_system_comes_from_styled_texts(self):
        self.assertEqual({s["name"] for s in self.r["styles"]}, {"Body/M", "Title/L"})

    def test_statuses(self):
        items = self.by_label()
        self.assertEqual(items["Ubuntu Regular 16/21"]["status"], "unbound")
        self.assertEqual(items["Ubuntu Regular 16/21"]["styles"], ["Body/M"])
        self.assertEqual(items["Ubuntu Bold 23.11/23.11"]["status"], "near")
        self.assertEqual(items["Inter Bold 20/24"]["status"], "off")

    def test_texts_inside_components_not_counted(self):
        self.assertNotIn("Inter Regular 13/16", self.by_label())


if __name__ == "__main__":
    unittest.main()
