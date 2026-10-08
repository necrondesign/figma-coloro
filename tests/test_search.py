"""Тесты поиска: основы слов, текст и названия, размер, компоненты, отвязанные копии."""

import tempfile
import unittest
from pathlib import Path

from coloro import db as dbm
from coloro import search
from coloro.filters import Filter
from coloro.load import load_file
from coloro.textnorm import norm, query_stems, stem

from test_foundation import FakeFigma, node, page


class Stems(unittest.TestCase):
    def test_word_forms_share_a_stem(self):
        for group in (("монета", "монеты", "монетами"), ("подписка", "подписку"), ("получить", "получите"),
                      ("settings", "setting"), ("buying", "buys")):
            self.assertEqual(len({stem(w) for w in group}), 1, group)

    def test_norm(self):
        self.assertEqual(norm("  Ёлка   ПРОДАНА "), "елка продана")

    def test_whole_words(self):
        from coloro.textnorm import whole_words
        self.assertTrue(whole_words("купить кота", "f:" + ",".join(query_stems("кот"))))
        self.assertTrue(whole_words("с котом", "f:" + ",".join(query_stems("кот"))))
        self.assertFalse(whole_words("котлета", "f:" + ",".join(query_stems("кот"))))
        self.assertTrue(whole_words("нет кнопок", "f:" + ",".join(query_stems("кнопка"))))
        self.assertTrue(whole_words("купить 100 монет!", "x:100 монет"))
        self.assertFalse(whole_words("купить 1100 монеток", "x:100 монет"))

    def test_fuzzy_helpers(self):
        from coloro import fuzzy
        self.assertEqual(fuzzy.distance("onbaording", "onboarding", 2), 1)   # перестановка — одна правка
        self.assertEqual(fuzzy.distance("кнопка", "кошка", 1), 2)
        self.assertEqual(fuzzy.other_layout("ghbdtn"), "привет")
        self.assertEqual(fuzzy.other_layout("руддщ"), "hello")
        self.assertEqual(fuzzy.translit("кнопка"), "knopka")
        self.assertEqual(fuzzy.translit("knopka"), "кнопка")
        from collections import Counter
        groups, also = fuzzy.expand("Onbaording", Counter({"onboarding": 5, "other": 1}), typos=True, layout=False)
        self.assertEqual(also, ["onboarding"])
        groups, also = fuzzy.expand("кот", Counter({"кит": 5}), typos=True, layout=False)
        self.assertEqual(also, [])                                       # в коротком слове опечаток не прощаем

    def test_short_words_kept_whole(self):
        self.assertEqual(query_stems("VIP 100 к"), ["vip", "100", "к"])


def text(nid, chars, name=None, **kw):
    return node(nid, "TEXT", name or chars, characters=chars, **kw)


class FakeWithComponents(FakeFigma):
    """Поддельная Figma, которая отдаёт справочник компонентов так же, как настоящая."""

    def nodes(self, key, ids, depth=None):
        res = super().nodes(key, ids, depth)
        for entry in res["nodes"].values():
            entry["components"] = {
                "C1": {"key": "k1", "name": "Size=B, Color=Pink", "componentSetId": "S1", "remote": True},
                "C2": {"key": "k2", "name": "Size=M, Color=Pink", "componentSetId": "S1", "remote": True},
                "C3": {"key": "k3", "name": "Avatar", "remote": False},
            }
            entry["componentSets"] = {"S1": {"key": "ks", "name": "Кнопка"}}
        return res


class Search(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = dbm.connect(Path(self.tmp.name) / "t.sqlite")
        f = FakeWithComponents([page("1:1", "Stage 1", [
            node("s1", "FRAME", "Магазин", children=[
                text("t1", "Купить 100 монет"),
                text("t2", "Монеты закончились"),
                text("t3", "Нет кнопок", name="Подсказка"),
                node("b1", "INSTANCE", "Кнопка", componentId="C1", overrides=[{"id": "x"}],
                     absoluteBoundingBox={"x": 0, "y": 0, "width": 56, "height": 56}),
                node("b2", "INSTANCE", "Кнопка", componentId="C2"),
                node("b3", "INSTANCE", "Avatar", componentId="C3"),
                node("d1", "FRAME", "кнопка", children=[text("t4", "Купить")]),   # отвязанная копия
            ])])])
        load_file(self.con, f, "K")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def found(self, kind, **q):
        cond, args, _ = search.condition(kind, q, self.con)
        res = search.layers(self.con, Filter(), cond, args, "K", "s1")
        return sorted(i["node_id"] for i in res["items"])

    def test_word_forms_any_order(self):
        self.assertEqual(self.found("text", q="монеты купите", where="text"), ["t1"])

    def test_fleeting_vowel(self):
        # «кнопка» находит «кнопок»: беглая гласная между согласными основы.
        self.assertIn("t3", self.found("text", q="кнопка", where="text"))

    def test_layer_name(self):
        self.assertIn("t3", self.found("text", q="подсказка", where="name"))

    def test_size(self):
        self.assertEqual(self.found("size", w="56", h="56"), ["b1"])

    def test_component_set_groups_variants(self):
        res = search.components(self.con, Filter())
        button = next(g for g in res["items"] if g["title"] == "Кнопка")
        self.assertEqual(button["instances"], 2)
        self.assertEqual(button["overridden"], 1)
        self.assertEqual(button["variants"]["Size"], {"B": 1, "M": 1})
        # Два варианта на одном экране — один экран, а не два.
        self.assertEqual(button["screens"], 1)
        self.assertTrue(button["remote"])

    def test_preview_layer(self):
        # Библиотечный компонент рисуется через свой инстанс, поставленный на экран напрямую.
        items = {g["title"]: g for g in search.components(self.con, Filter())["items"]}
        self.assertEqual(items["Кнопка"]["preview"], ["K", "b1"])
        self.assertEqual(items["Avatar"]["preview"], ["K", "b3"])

    def test_local_component_previews_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = dbm.connect(Path(tmp) / "t.sqlite")
            f = FakeWithComponents([page("1:1", "Stage", [node("C3", "COMPONENT", "Avatar"),
                                                          node("s", "FRAME", children=[node("b", "INSTANCE", componentId="C3")])])])
            load_file(con, f, "K")
            g = search.components(con, Filter())["items"][0]
            self.assertEqual(g["preview"], ["K", "C3"])
            con.close()

    def test_search_by_set(self):
        self.assertEqual(self.found("component", set="Кнопка"), ["b1", "b2"])

    def test_search_by_variant(self):
        self.assertEqual(self.found("component", set="Кнопка", variant="Size=B"), ["b1"])

    def test_detached_copy(self):
        # Кадр «кнопка» с маленькой буквы — сравнение с компонентом «Кнопка» без учёта регистра,
        # в том числе для кириллицы, которую встроенная lower() SQLite не понимает.
        ids = [i["node_id"] for i in search.detached(self.con, Filter())["items"]]
        self.assertEqual(ids, ["d1"])

    def test_variant_props(self):
        self.assertEqual(search.variant_props("Size=B, Color=Pink"), {"Size": "B", "Color": "Pink"})
        self.assertEqual(search.variant_props("Avatar"), {})


if __name__ == "__main__":
    unittest.main()
