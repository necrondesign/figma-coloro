"""Тесты фундамента: правила-метки, извлечение цветов, загрузка без потерь.

Запуск без установки чего-либо:  python3 -m unittest discover -s tests
"""

import copy
import tempfile
import threading
import unittest
from pathlib import Path

from coloro import db as dbm
from coloro import rules
from coloro.figma import FigmaError, Truncated
from coloro.load import load_file
from coloro.walk import Ctx, Out, paints_of, walk


def solid(r, g, b, a=1.0, opacity=None, **extra):
    p = {"type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": a}}
    if opacity is not None:
        p["opacity"] = opacity
    p.update(extra)
    return p


def node(nid, ntype="RECTANGLE", name=None, children=None, **extra):
    n = {"id": nid, "type": ntype, "name": name or nid,
         "absoluteBoundingBox": {"x": 0, "y": 0, "width": 10, "height": 10}}
    if children is not None:
        n["children"] = children
    n.update(extra)
    return n


class Intern:
    def __init__(self):
        self.vals = {}

    def __call__(self, v):
        if not v:
            return None
        return self.vals.setdefault(v, len(self.vals) + 1)


# ---------------------------------------------------------------- правила

class Rules(unittest.TestCase):
    def test_archive_spellings(self):
        for name in ("Archive", "Stage 1 archive", "Архив", "Старое (архив)", "arhive", "Stage 1 arсhive"):
            self.assertTrue(rules.is_archive(name), name)

    def test_cyrillic_s_is_not_latin(self):
        # Ловушка, ради которой вариант и заведён: «с» кириллическая, на вид не отличить.
        self.assertNotEqual("arсhive", "archive")
        self.assertTrue(rules.is_archive("arсhive"))

    def test_not_archive(self):
        for name in ("Stage 1", "Local components", "Search", "Cover"):
            self.assertFalse(rules.is_archive(name), name)

    def test_name_matches(self):
        self.assertTrue(rules.name_matches("Stage 3 — Shop", ["stage"]))
        self.assertTrue(rules.name_matches("anything", []))
        self.assertTrue(rules.name_matches("anything", None))
        self.assertFalse(rules.name_matches("Flow", ["stage"]))

    def test_parse_link(self):
        self.assertEqual(rules.parse_link("https://www.figma.com/design/AbC123/Name?node-id=12-34&t=x"),
                         ("AbC123", "12:34"))
        self.assertEqual(rules.parse_link("https://www.figma.com/file/AbC123/Name"), ("AbC123", None))
        self.assertEqual(rules.parse_link("https://www.figma.com/design/AbC123/branch/BrX9/Name"), ("BrX9", None))
        self.assertEqual(rules.parse_link("https://www.figma.com/board/AbC123/Jam"), ("AbC123", None))
        with self.assertRaises(rules.LinkError):
            rules.parse_link("https://example.com/whatever")


# ---------------------------------------------------------------- цвета

class Paints(unittest.TestCase):
    def test_solid_alpha_includes_paint_opacity(self):
        # У сплошной краски прозрачность цвета умножается на прозрачность краски:
        # это то, что показывает пипетка.
        out = paints_of(node("a", fills=[solid(1, 0, 0, a=0.5, opacity=0.5)]), {}, Intern())
        self.assertEqual(out[0][2:4], ("FF0000", 25))

    def test_gradient_stop_alpha_is_its_own(self):
        # У стопа — только его прозрачность. Прозрачность краски целиком не умножается.
        grad = {"type": "GRADIENT_LINEAR", "opacity": 0.5, "gradientStops": [
            {"position": 0, "color": {"r": 0, "g": 0, "b": 1, "a": 0.8}},
            {"position": 1, "color": {"r": 0, "g": 1, "b": 0, "a": 1.0}},
        ]}
        out = paints_of(node("a", fills=[grad]), {}, Intern())
        self.assertEqual([(o[1], o[2], o[3]) for o in out], [("stop", "0000FF", 80), ("stop", "00FF00", 100)])

    def test_same_gradient_same_recipe(self):
        intern = Intern()
        g = {"type": "GRADIENT_LINEAR", "gradientStops": [
            {"position": 0, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
            {"position": 1, "color": {"r": 0, "g": 0, "b": 1, "a": 1}}]}
        a = paints_of(node("a", fills=[g]), {}, intern)
        b = paints_of(node("b", fills=[copy.deepcopy(g)]), {}, intern)
        self.assertEqual(a[0][5], b[0][5])

    def test_text_style_is_not_a_color_style(self):
        # Текстовый стиль — это шрифт и кегль. Цвет текста, набранный вручную, — вручную.
        n = node("t", "TEXT", fills=[solid(0, 0, 0)], styles={"text": "S1"})
        out = paints_of(n, {"S1": {"name": "Body/M"}}, Intern())
        self.assertIsNone(out[0][4])

    def test_fill_style_counts(self):
        n = node("t", "TEXT", fills=[solid(0, 0, 0)], styles={"fill": "S2"})
        out = paints_of(n, {"S2": {"name": "Text/Primary"}}, Intern())
        self.assertEqual(out[0][4], "s:Text/Primary")

    def test_variable_on_layer_and_on_paint(self):
        on_layer = node("a", fills=[solid(1, 1, 1)], boundVariables={"fills": [{"id": "V1"}]})
        on_paint = node("b", fills=[solid(1, 1, 1, boundVariables={"color": {"id": "V1"}})])
        self.assertEqual(paints_of(on_layer, {}, Intern())[0][4], "v")
        # Переменная только на самой краске — тоже привязка. Проверено на живых соединительных линиях.
        self.assertEqual(paints_of(on_paint, {}, Intern())[0][4], "v")

    def test_invisible_paint_skipped(self):
        out = paints_of(node("a", fills=[solid(1, 0, 0, visible=False), solid(0, 1, 0)]), {}, Intern())
        self.assertEqual([o[2] for o in out], ["00FF00"])

    def test_hidden_and_sections_are_labels_not_drops(self):
        tree = node("s", "SECTION", "Для арта", children=[
            node("f", "FRAME", visible=False, children=[node("r", fills=[solid(1, 0, 0)])])])
        out, intern = Out(), Intern()
        walk(tree, Ctx("K", "P"), {}, intern, {}, "now", out)
        rows = {r[2]: r for r in out.nodes}
        self.assertEqual(len(rows), 3)                 # ничего не выброшено
        self.assertEqual(rows["r"][6], 1)               # скрыт через родителя
        self.assertEqual(rows["r"][7], intern("Для арта"))
        self.assertEqual(len(out.paints), 1)            # цвет записан, решает фильтр


# ---------------------------------------------------------------- загрузка

def doc(pages):
    return {"name": "File", "version": "v1", "lastModified": "2026-10-01T00:00:00Z",
            "document": {"id": "0:0", "type": "DOCUMENT", "children": pages}}


class FakeFigma:
    """Поддельная Figma: отдаёт заданное дерево и умеет обрываться и падать по заказу."""

    def __init__(self, pages, version="v1"):
        self.pages = pages
        self.version = version
        self.truncate_over = None       # обрывать ответ, если в нём больше стольких слоёв
        self.fail_ids = set()           # на этих id отвечать ошибкой
        self.calls = []

    def _index(self):
        idx = {}
        stack = list(self.pages)
        while stack:
            n = stack.pop()
            idx[n["id"]] = n
            stack.extend(n.get("children") or [])
        return idx

    def file_head(self, key, depth=1):
        self.calls.append(("head", depth))
        pages = []
        for p in self.pages:
            q = {k: v for k, v in p.items() if k != "children"}
            if depth >= 2:
                q["children"] = [{k: v for k, v in c.items() if k != "children"} for c in p.get("children") or []]
            pages.append(q)
        d = doc(pages)
        d["version"] = self.version
        return d

    def file_meta(self, key):
        self.calls.append(("meta",))
        if getattr(self, "no_meta", False):
            raise FigmaError("not_found", "файл не найден — проверьте ссылку и доступ", 404)
        return {"name": "File", "version": self.version}

    def nodes(self, key, ids, depth=None):
        self.calls.append(("nodes", tuple(ids), depth))
        if self.fail_ids & set(ids):
            raise FigmaError("figma_unavailable", "Figma временно не отвечает", 503)
        idx = self._index()
        res = {}
        size = 0
        for i in ids:
            n = copy.deepcopy(idx[i])
            if depth == 1:
                n["children"] = [{k: v for k, v in c.items() if k != "children"} for c in n.get("children") or []]
            res[i] = {"document": n, "styles": dict(getattr(self, "styles", {}))}
            stack = [n]
            while stack:
                m = stack.pop()
                size += 1
                stack.extend(m.get("children") or [])
        if self.truncate_over is not None and depth is None and size > self.truncate_over:
            raise Truncated()
        return {"nodes": res}


def page(pid, name, frames):
    return {"id": pid, "type": "CANVAS", "name": name, "children": frames}


def frame(fid, n_rects=2, color=(1, 0, 0)):
    return node(fid, "FRAME", children=[node(f"{fid}/r{i}", fills=[solid(*color)]) for i in range(n_rects)])


class Load(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = dbm.connect(Path(self.tmp.name) / "t.sqlite")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def count(self, table, page=None):
        if page:
            return self.con.execute(f"SELECT COUNT(*) FROM {table} WHERE page_id = ?", (page,)).fetchone()[0]
        return self.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_loads_everything_with_labels(self):
        f = FakeFigma([page("1:1", "Stage 1", [frame("a")]), page("2:2", "Archive", [frame("b")])])
        rep = load_file(self.con, f, "K")
        self.assertEqual(rep["status"], "ok")
        # Архив загружен — с меткой, а не выброшен.
        self.assertEqual(self.count("paints"), 4)
        archived = dict(self.con.execute("SELECT name, archived FROM pages"))
        self.assertEqual(archived, {"Stage 1": 0, "Archive": 1})

    def test_reload_never_doubles(self):
        f = FakeFigma([page("1:1", "Stage 1", [frame("a")])])
        load_file(self.con, f, "K")
        f.version = "v2"
        load_file(self.con, f, "K")
        load_file(self.con, f, "K", force=True)
        self.assertEqual(self.count("paints"), 2)
        self.assertEqual(self.count("nodes"), 3)

    def test_unchanged_file_is_not_downloaded(self):
        f = FakeFigma([page("1:1", "Stage 1", [frame("a")])])
        load_file(self.con, f, "K")
        f.calls.clear()
        rep = load_file(self.con, f, "K")
        self.assertEqual(rep["status"], "unchanged")
        self.assertEqual(f.calls, [("meta",)])        # только лёгкий запрос версии

    def test_unchanged_without_meta_falls_back(self):
        f = FakeFigma([page("1:1", "Stage 1", [frame("a")])])
        load_file(self.con, f, "K")
        f.calls.clear()
        f.no_meta = True
        rep = load_file(self.con, f, "K")
        self.assertEqual(rep["status"], "unchanged")
        self.assertEqual(f.calls, [("meta",), ("head", 1)])

    def test_new_version_seen_through_meta(self):
        f = FakeFigma([page("1:1", "Stage 1", [frame("a")])])
        load_file(self.con, f, "K")
        f.version = "v2"
        rep = load_file(self.con, f, "K")
        self.assertEqual(rep["pages_loaded"], ["Stage 1"])

    def test_widened_pages_load_the_new_page(self):
        # Версия та же, но теперь нужна страница, которую раньше пропускали: её надо докачать.
        f = FakeFigma([page("1:1", "Stage 1", [frame("a")]), page("2:2", "Draft", [frame("b")])])
        load_file(self.con, f, "K", ["stage"])
        rep = load_file(self.con, f, "K", ["stage", "draft"])
        self.assertEqual(rep["pages_loaded"], ["Draft"])
        rep = load_file(self.con, f, "K", ["stage", "draft"])
        self.assertEqual(rep["status"], "unchanged")

    def test_failed_page_keeps_old_data_and_others_load(self):
        f = FakeFigma([page("1:1", "Stage 1", [frame("a")]), page("2:2", "Stage 2", [frame("b")])])
        load_file(self.con, f, "K")
        f.version = "v2"
        f.fail_ids = {"a"}
        rep = load_file(self.con, f, "K")
        self.assertEqual(rep["status"], "partial")
        self.assertEqual(self.count("paints", "1:1"), 2)          # прежние данные на месте
        self.assertEqual(self.count("paints", "2:2"), 2)
        st = dict(self.con.execute("SELECT page_id, status FROM pages"))
        self.assertEqual(st, {"1:1": "failed", "2:2": "ok"})
        # Следующее обновление качает только упавшую страницу.
        f.fail_ids = set()
        f.calls.clear()
        rep = load_file(self.con, f, "K")
        self.assertEqual(rep["pages_loaded"], ["Stage 1"])

    def test_truncated_response_is_split_and_recovered(self):
        f = FakeFigma([page("1:1", "Big", [frame(f"f{i}", n_rects=5) for i in range(6)])])
        f.truncate_over = 7          # больше одного кадра за раз не пролезает
        rep = load_file(self.con, f, "K")
        self.assertEqual(rep["status"], "ok")
        self.assertEqual(self.count("paints"), 30)

    def test_single_node_too_big_is_opened_up(self):
        f = FakeFigma([page("1:1", "Huge", [frame("big", n_rects=10)])])
        f.truncate_over = 3
        rep = load_file(self.con, f, "K")
        self.assertEqual(rep["status"], "ok")
        self.assertEqual(self.count("paints"), 10)
        parent = self.con.execute("SELECT parent_id FROM nodes WHERE id = 'big/r0'").fetchone()[0]
        self.assertEqual(parent, "big")              # связь с родителем не потерялась

    def test_stop_never_leaves_half_a_page(self):
        f = FakeFigma([page("1:1", "Stage 1", [frame(f"f{i}") for i in range(20)])])
        stop = threading.Event()
        stop.set()
        rep = load_file(self.con, f, "K", stop=stop)
        self.assertEqual(rep["status"], "stopped")
        self.assertEqual(self.count("nodes"), 0)

    def test_first_seen_survives_reload(self):
        f = FakeFigma([page("1:1", "Stage 1", [frame("a")])])
        load_file(self.con, f, "K")
        first = self.con.execute("SELECT first_seen FROM nodes WHERE id = 'a'").fetchone()[0]
        f.version = "v2"
        load_file(self.con, f, "K")
        again = self.con.execute("SELECT first_seen FROM nodes WHERE id = 'a'").fetchone()[0]
        self.assertEqual(first, again)

    def test_deleted_page_leaves_the_base(self):
        f = FakeFigma([page("1:1", "Stage 1", [frame("a")]), page("2:2", "Stage 2", [frame("b")])])
        load_file(self.con, f, "K")
        f.pages = f.pages[:1]
        f.version = "v2"
        load_file(self.con, f, "K")
        self.assertEqual(self.count("pages"), 1)
        self.assertEqual(self.count("paints", "2:2"), 0)


if __name__ == "__main__":
    unittest.main()
