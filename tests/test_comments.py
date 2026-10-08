"""Тесты комментариев: забор из Figma, экран обсуждения, ответы, сроки, нет прав."""

import tempfile
import unittest
from pathlib import Path

from coloro import comments
from coloro import db as dbm
from coloro.figma import FigmaError
from coloro.filters import Filter
from coloro.load import load_file

from test_foundation import FakeFigma, node, page


class FakeComments(FakeFigma):
    def __init__(self, pages, forbid=False):
        super().__init__(pages)
        self.forbid = forbid

    def get_json(self, path, params=None):
        if self.forbid:
            raise FigmaError("forbidden", "no access", 403)
        if path.endswith("/comments"):
            return {"comments": [
                {"id": "1", "message": "Кнопка мелкая", "user": {"handle": "Аня"}, "created_at": "2020-01-01T10:00:00Z",
                 "resolved_at": None, "client_meta": {"node_id": "b", "node_offset": {"x": 1, "y": 1}}},
                {"id": "2", "parent_id": "1", "message": "Поправлю", "user": {"handle": "Боря"}, "created_at": "2020-01-02T10:00:00Z"},
                {"id": "3", "message": "Ок", "user": {"handle": "Аня"}, "created_at": "2020-01-03T10:00:00Z",
                 "resolved_at": "2020-01-04T10:00:00Z", "client_meta": {"x": 5, "y": 5}},
            ]}
        raise AssertionError(path)


class Comments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = dbm.connect(Path(self.tmp.name) / "t.sqlite")
        self.pages = [page("1:1", "Stage", [node("s", "FRAME", "Корзина", children=[node("b", "INSTANCE", "Кнопка")])])]
        load_file(self.con, FakeFigma(self.pages), "K")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_threads(self):
        comments.fetch(self.con, FakeComments(self.pages), "K")
        d = comments.report(self.con, Filter())
        t = {x["id"]: x for x in d["threads"]}
        self.assertEqual(set(t), {"1", "3"})                         # обсуждения, без ответов
        self.assertEqual((t["1"]["screen"], t["1"]["open"], t["1"]["stale"]), ("Корзина", True, True))
        self.assertEqual([r["message"] for r in t["1"]["replies"]], ["Поправлю"])
        self.assertEqual(t["1"]["people"], ["Аня", "Боря"])
        self.assertEqual((t["3"]["open"], t["3"]["open_days"]), (False, 1))
        self.assertEqual((d["totals"]["open"], d["totals"]["unanswered"], d["totals"]["median_days"]), (1, 0, 1))
        self.assertEqual(d["screens"][0]["screen"], "Корзина")
        self.assertEqual(d["access"], [])

    def test_missing_access_is_reported_not_fatal(self):
        comments.fetch(self.con, FakeComments(self.pages, forbid=True), "K")
        d = comments.report(self.con, Filter())
        self.assertEqual(d["access"], ["File"])
        self.assertTrue(d["checked"])


if __name__ == "__main__":
    unittest.main()
