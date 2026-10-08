"""Тесты версий и комментариев: забор из Figma, экран комментария, листание истории, нет прав."""

import tempfile
import unittest
from pathlib import Path

from coloro import activity
from coloro import db as dbm
from coloro.figma import FigmaError
from coloro.filters import Filter
from coloro.load import load_file

from test_foundation import FakeFigma, node, page


class FakeActivity(FakeFigma):
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
        if path.endswith("/versions"):
            if (params or {}).get("after") == "p2":
                return {"versions": [{"id": "v1", "created_at": "2020-01-01T00:00:00Z", "label": "Старт", "user": {"handle": "Аня"}}],
                        "pagination": {}}
            return {"versions": [{"id": "v2", "created_at": "2020-02-01T00:00:00Z", "label": None, "user": {"handle": "Боря"}}],
                    "pagination": {"next_page": "https://api.figma.com/v1/files/K/versions?page_size=50&after=p2"}}
        raise AssertionError(path)


class Activity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = dbm.connect(Path(self.tmp.name) / "t.sqlite")
        self.pages = [page("1:1", "Stage", [node("s", "FRAME", "Корзина", children=[node("b", "INSTANCE", "Кнопка")])])]
        load_file(self.con, FakeFigma(self.pages), "K")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_comments_and_versions(self):
        activity.fetch(self.con, FakeActivity(self.pages), "K")
        d = activity.report(self.con, Filter())
        t = {x["id"]: x for x in d["comments"]}
        self.assertEqual(set(t), {"1", "3"})                         # обсуждения, без ответов
        self.assertEqual((t["1"]["screen"], t["1"]["open"], t["1"]["stale"]), ("Корзина", True, True))
        self.assertEqual([r["message"] for r in t["1"]["replies"]], ["Поправлю"])
        self.assertFalse(t["3"]["open"])
        self.assertEqual([v["id"] for v in d["versions"]], ["v2", "v1"])   # вторая страница истории тоже
        self.assertEqual(d["totals"]["named"], 1)
        self.assertEqual(d["access"], {})

    def test_missing_access_is_reported_not_fatal(self):
        activity.fetch(self.con, FakeActivity(self.pages, forbid=True), "K")
        d = activity.report(self.con, Filter())
        self.assertEqual(sorted(d["access"]), ["comments", "versions"])
        self.assertTrue(d["checked"])


if __name__ == "__main__":
    unittest.main()
