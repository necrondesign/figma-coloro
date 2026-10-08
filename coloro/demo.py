"""Демо-проект: выдуманное мобильное приложение магазина, чтобы попробовать инструмент без Figma.

    python3 -m coloro demo

Всё здесь придумано: файлы, экраны, тексты, люди в комментариях, цвета. Данные собираются
тем же загрузчиком, что и настоящие файлы, — через поддельную Figma, которая отдаёт заранее
построенное дерево. В макетах нарочно есть типичные проблемы: цвет почти как токен, значение
токена, набранное вручную, текст без стиля, отступ мимо шкалы, нечитаемый серый текст,
кнопка на необычном фоне, отвязанная копия компонента, открытые обсуждения. Так каждому
разделу есть что показать.

Ключи файлов нарочно не похожи на настоящие ключи Figma: ссылки из демо никуда не ведут.
"""

from __future__ import annotations

import copy
import json
import random
import time
from pathlib import Path

from . import db as dbm
from . import health, memo, tokens
from .figma import FigmaError
from .load import load_file

DEFAULT_DB = Path.home() / ".coloro" / "demo.sqlite"
APP, DS = "demo-shop-app", "demo-shop-design-system"
NAMES = {APP: "Shop app", DS: "Shop design system"}
COLL = "demo-colors"
LIGHT, DARK = "1:0", "1:1"

# Справочник: переменные с двумя темами. Ключ — как у библиотечной переменной в Figma.
PALETTE = [
    ("Text/Primary", "#1E1E1E", "#F5F5F7"), ("Text/Secondary", "#5A5F68", "#B1B5BD"),
    ("Text/On accent", "#FFFFFF", "#FFFFFF"), ("Surface/Base", "#FFFFFF", "#16171B"),
    ("Surface/Raised", "#F5F6F8", "#22242A"), ("Surface/Inverse", "#16171B", "#FFFFFF"),
    ("Brand/Primary", "#0B6BCB", "#3AA5F2"), ("Brand/Pressed", "#08559F", "#1E8FDE"),
    ("Brand/Subtle", "#E3F1FC", "#123247"), ("Status/Success", "#14AE5C", "#2BC271"),
    ("Status/Warning", "#FF8A1F", "#FF9F43"), ("Status/Danger", "#E5484D", "#F2555A"),
    ("Border/Subtle", "#E4E7EE", "#33363D"), ("Overlay/Dim", "#000000@40", "#000000@60"),
]
NUMBERS = [("Space/4", 4), ("Space/8", 8), ("Space/12", 12), ("Space/16", 16), ("Space/24", 24),
           ("Space/32", 32), ("Radius/8", 8), ("Radius/12", 12), ("Radius/16", 16), ("Radius/Full", 999)]


def _key(name: str) -> str:
    return "demo" + "".join(c for c in name.lower() if c.isalnum())


def _rgb(hexv: str) -> dict:
    h, _, a = hexv.lstrip("#").partition("@")
    return {"r": int(h[0:2], 16) / 255, "g": int(h[2:4], 16) / 255, "b": int(h[4:6], 16) / 255,
            "a": int(a) / 100 if a else 1}


def library() -> list[dict]:
    rows = [{"name": n, "type": "color", "collection": "Colors", "key": _key(n),
             "values": {"Light": light, "Dark": dark}} for n, light, dark in PALETTE]
    rows += [{"name": n, "type": "number", "collection": "Spacing and radius", "key": _key(n), "value": v}
             for n, v in NUMBERS]
    return rows


TOKEN = {n: (light, dark) for n, light, dark in PALETTE}


class Builder:
    """Строит дерево слоёв как ответ Figma: id по порядку, рамки в абсолютных координатах."""

    def __init__(self, prefix: str):
        self.prefix, self.n = prefix, 0

    def id(self) -> str:
        self.n += 1
        return f"{self.prefix}:{self.n}"

    def node(self, kind, name, x, y, w, h, children=None, **extra):
        n = {"id": self.id(), "type": kind, "name": name,
             "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h}}
        if children is not None:
            n["children"] = children
        n.update(extra)
        return n


def fill(token: str | None = None, hexv: str | None = None, dark: bool = False, opacity: float | None = None):
    """Заливка: привязанная к переменной (token) или набранная вручную (hexv)."""
    if token:
        p = {"type": "SOLID", "color": _rgb(TOKEN[token][1 if dark else 0]),
             "boundVariables": {"color": {"type": "VARIABLE_ALIAS", "id": f"VariableID:{_key(token)}/1:{len(token)}"}}}
    else:
        p = {"type": "SOLID", "color": _rgb(hexv)}
    if opacity is not None:
        p["opacity"] = opacity
    return p


FONTS = {"H1": ("Bold", 700, 28, 34), "H2": ("Semi Bold", 600, 20, 26), "Body": ("Regular", 400, 16, 22),
         "Caption": ("Regular", 400, 13, 18), "Button": ("Semi Bold", 600, 16, 20)}
TEXT_STYLES = {"H1": "S:h1", "H2": "S:h2", "Body": "S:body", "Caption": "S:caption", "Button": "S:button"}


def text(b: Builder, chars, x, y, w, style="Body", token="Text/Primary", hexv=None, dark=False, styled=True,
         size=None, **extra):
    st, weight, fs, lh = FONTS[style]
    if size:
        fs, lh = size, round(size * 1.35)
    n = b.node("TEXT", chars[:40], x, y, w, lh, characters=chars, fills=[fill(token if not hexv else None, hexv, dark)],
               style={"fontFamily": "Inter", "fontStyle": st, "fontWeight": weight, "fontSize": fs,
                      "lineHeightPx": lh, "letterSpacing": 0}, **extra)
    if styled:
        n["styles"] = {"text": TEXT_STYLES[style]}
    return n


def button(b: Builder, label, x, y, size="L", state="Default", w=None, dark=False):
    w = w or {"L": 327, "M": 160, "S": 96}[size]
    h = {"L": 52, "M": 44, "S": 32}[size]
    return b.node("INSTANCE", "Button", x, y, w, h, componentId=f"C:btn-{size}-{state}".lower(),
                  fills=[fill("Brand/Primary" if state != "Disabled" else "Border/Subtle", dark=dark)],
                  cornerRadius=12, layoutMode="HORIZONTAL", itemSpacing=8,
                  paddingTop=14, paddingBottom=14, paddingLeft=24, paddingRight=24, primaryAxisAlignItems="CENTER",
                  children=[text(b, label, x + 24, y + 16, w - 48, "Button", "Text/On accent", dark=dark)])


def card(b: Builder, x, y, title, price, dark=False, radius=12, pad=16, shadow="style", gap=8, img="img-sneakers"):
    """Карточка товара. radius, pad, gap и тень можно испортить — так получаются находки."""
    eff = {"type": "DROP_SHADOW", "visible": True, "color": {"r": 0, "g": 0, "b": 0, "a": 0.08},
           "offset": {"x": 0, "y": 4}, "radius": 16, "spread": 0}
    extra = {"effects": [eff]}
    if shadow == "style":
        extra["styles"] = {"effect": "S:shadow"}
    elif shadow == "off":
        extra["effects"] = [{**eff, "offset": {"x": 0, "y": 6}, "radius": 20, "color": {"r": 0, "g": 0, "b": 0, "a": 0.14}}]
    return b.node("FRAME", "Product card", x, y, 156, 236, fills=[fill("Surface/Raised", dark=dark)],
                  cornerRadius=radius, layoutMode="VERTICAL", itemSpacing=gap,
                  paddingTop=pad, paddingBottom=pad, paddingLeft=pad, paddingRight=pad, **extra,
                  children=[b.node("RECTANGLE", "Photo", x + pad, y + pad, 124, 124, cornerRadius=8,
                                   fills=[{"type": "IMAGE", "imageRef": img, "scaleMode": "FILL"}]),
                            text(b, title, x + pad, y + 150, 124, "Body", dark=dark),
                            text(b, price, x + pad, y + 176, 124, "H2", "Brand/Primary", dark=dark),
                            *([] if dark else [button(b, "Add", x + pad, y + 200, size="S")])])


def screen(b: Builder, name, x, children, dark=False, h=812):
    extra = {"explicitVariableModes": {f"VariableCollectionId:{COLL}": DARK}} if dark else {}
    return b.node("FRAME", name, x, 0, 375, h, fills=[fill("Surface/Base", dark=dark)], children=children, **extra)


def app_pages(stage: int) -> list[dict]:
    """Файл приложения. stage 0 — давнее состояние (хуже), 2 — текущее: часть находок исправлена."""
    rnd = random.Random(7)
    b = Builder("1")
    fix = lambda level: stage >= level                       # к этому этапу исправлено
    pages = []

    # ---------- Каталог
    s = []
    for i, dark in enumerate((False, False, True)):
        x0 = i * 450
        kids = [text(b, "Sneakers" if i < 2 else "Night drop", x0 + 24, 64, 327, "H1", dark=dark),
                text(b, "Free delivery from $50", x0 + 24, 104, 327, "Caption", "Text/Secondary", dark=dark)]
        for r in range(2):
            for c in range(2):
                # Одна карточка испорчена всегда, вторая — только в давних версиях.
                bad = (r, c) == (1, 1) or ((r, c) == (0, 1) and not fix(1))
                kids.append(card(b, x0 + 24 + c * 171, 144 + r * 252, rnd.choice(["Runner 2", "Court Low", "Trail Pro", "Daily"]),
                                 f"${rnd.choice([79, 89, 99, 129])}", dark=dark,
                                 radius=13 if bad else 12, pad=15 if bad else 16, shadow="off" if bad else "style",
                                 img=["img-sneakers", "img-boots", "img-sneakers", "img-sandals"][r * 2 + c]))
        if not dark:
            kids.append(button(b, "Show 24 items", x0 + 24, 680))
        s.append(screen(b, ["Catalog", "Catalog / Filters applied", "Catalog / Dark"][i], x0, kids, dark=dark))
    # Баннер с градиентом и белым текстом на нём.
    s.append(screen(b, "Catalog / Promo", 1350, [
        b.node("RECTANGLE", "Promo banner", 1374, 64, 327, 160, cornerRadius=16,
               fills=[{"type": "GRADIENT_LINEAR", "gradientStops": [
                   {"position": 0, "color": _rgb("#0B6BCB")}, {"position": 1, "color": _rgb("#7B61FF")}]}]),
        text(b, "Autumn sale −30%", 1398, 96, 280, "H1", "Text/On accent"),
        text(b, "Only this week", 1398, 140, 280, "Body", "Text/On accent"),
        button(b, "Shop the sale", 1374, 248),
    ]))
    pages.append({"id": "10:0", "type": "CANVAS", "name": "Catalog", "children": s})

    # ---------- Оформление заказа
    s = []
    for i in range(3):
        x0 = i * 450
        kids = [text(b, ["Cart", "Delivery", "Payment"][i], x0 + 24, 64, 327, "H1"),
                text(b, "Add promo code", x0 + 24, 110, 327, "Body", "Brand/Primary"),
                # Подсказка светло-серым: нечитаемо на белом.
                text(b, "Delivery in 2–3 days. Return within 30 days.", x0 + 24, 600, 327, "Caption",
                     hexv="#B1B5BD" if not fix(2) else None, token="Text/Secondary"),
                # Цвет почти как токен: #0C6CCA вместо #0B6BCB.
                b.node("RECTANGLE", "Divider", x0 + 24, 140, 327, 1, fills=[fill(hexv="#E4E7EF")]),
                b.node("FRAME", "Order summary", x0 + 24, 160, 327, 140, cornerRadius=12,
                       fills=[fill("Surface/Raised")], layoutMode="VERTICAL", itemSpacing=10,
                       paddingTop=16, paddingBottom=16, paddingLeft=16, paddingRight=16,
                       children=[text(b, "Subtotal  $178", x0 + 40, 176, 290, "Body", styled=fix(1)),
                                 text(b, "Delivery  Free", x0 + 40, 204, 290, "Body", hexv="#0C6CCA"),
                                 text(b, "Total  $178", x0 + 40, 232, 290, "H2", size=19, styled=False)])]
        # Значение токена набрано вручную: #14AE5C без переменной.
        kids.append(b.node("FRAME", "Badge / In stock", x0 + 24, 320, 96, 24, cornerRadius=12,
                           fills=[fill(hexv="#14AE5C")], children=[text(b, "In stock", x0 + 34, 324, 76, "Caption", "Text/On accent")]))
        # Предупреждение: белый на оранжевом — контраст ниже нормы.
        kids.append(b.node("FRAME", "Banner / Warning", x0 + 24, 360, 327, 48, cornerRadius=8,
                           fills=[fill("Status/Warning")], children=[text(b, "Only 2 left in your size", x0 + 40, 374, 290, "Body", "Text/On accent")]))
        kids.append(button(b, ["Checkout", "Continue", "Pay $178"][i], x0 + 24, 720))
        s.append(screen(b, ["Cart", "Delivery", "Payment"][i], x0, kids))
    # Тёмная плашка внизу, на ней — кнопка: необычное место для кнопки.
    x0 = 1350
    s.append(screen(b, "Payment / Success", x0, [
        text(b, "Thank you!", x0 + 24, 64, 327, "H1"),
        text(b, "Order #20481 is on its way", x0 + 24, 110, 327, "Body", "Text/Secondary"),
        b.node("FRAME", "Bottom sheet", x0, 612, 375, 200, fills=[fill("Surface/Inverse")], children=[
            text(b, "Track your order", x0 + 24, 636, 327, "H2", "Surface/Base"),
            button(b, "Open tracking", x0 + 24, 720)]),
    ]))
    pages.append({"id": "20:0", "type": "CANVAS", "name": "Checkout", "children": s})

    # ---------- Профиль: тексты повторяются по-разному, рамка-копия кнопки, скрытый слой
    x0 = 0
    s = [screen(b, "Profile", x0, [
        text(b, "Profile", x0 + 24, 64, 327, "H1"),
        text(b, "Add to cart", x0 + 24, 120, 327, "Body"), text(b, "Add to Cart", x0 + 24, 150, 327, "Body", styled=False),
        b.node("FRAME", "Button", x0 + 24, 720, 327, 52, cornerRadius=12, fills=[fill(hexv="#0C6CCA")],
               children=[text(b, "Sign out", x0 + 48, 736, 280, "Button", "Text/On accent")]),
        b.node("FRAME", "Frame 12", x0 + 24, 200, 327, 80, fills=[fill("Surface/Raised")], cornerRadius=12),
        b.node("RECTANGLE", "Old banner", x0 + 24, 300, 327, 80, visible=False, fills=[fill(hexv="#FF5C5C")]),
    ]), screen(b, "Settings", 450, [
        text(b, "Settings", 474, 64, 327, "H1"),
        *[text(b, t, 474, 120 + i * 48, 327, "Body") for i, t in enumerate(["Notifications", "Language", "Privacy", "Help"])],
        button(b, "Save", 474, 720, size="M", state="Disabled"),
    ])]
    pages.append({"id": "30:0", "type": "CANVAS", "name": "Profile", "children": s})
    pages.append({"id": "40:0", "type": "CANVAS", "name": "Archive", "children": [
        screen(b, "Old catalog", 0, [text(b, "Catalog v1", 24, 64, 327, "H1", hexv="#333333", styled=False)])]})
    return pages


def ds_pages() -> list[dict]:
    """Файл библиотеки: набор Button с вариантами."""
    b = Builder("2")
    variants = []
    for i, (size, state) in enumerate((s, st) for s in ("L", "M", "S") for st in ("Default", "Pressed", "Disabled")):
        w = {"L": 327, "M": 160, "S": 96}[size]
        variants.append(b.node("COMPONENT", f"Size={size}, State={state}", (i % 3) * 360, (i // 3) * 80, w, 52,
                               fills=[fill({"Default": "Brand/Primary", "Pressed": "Brand/Pressed",
                                                      "Disabled": "Border/Subtle"}[state])], cornerRadius=12,
                               children=[text(b, "Button", (i % 3) * 360 + 24, (i // 3) * 80 + 16, w - 48, "Button", "Text/On accent")]))
    sset = b.node("COMPONENT_SET", "Button", 0, 0, 1100, 260, children=variants)
    return [{"id": "50:0", "type": "CANVAS", "name": "Components", "children": [sset]}]


STYLES = {"S:h1": {"name": "Heading/H1", "styleType": "TEXT"}, "S:h2": {"name": "Heading/H2", "styleType": "TEXT"},
          "S:body": {"name": "Body/Regular", "styleType": "TEXT"}, "S:caption": {"name": "Body/Caption", "styleType": "TEXT"},
          "S:button": {"name": "Button/Label", "styleType": "TEXT"}, "S:shadow": {"name": "Shadow/Card", "styleType": "EFFECT"}}
COMPONENTS = {f"C:btn-{s}-{st}".lower(): {"key": f"demo-btn-{s}-{st}".lower(), "name": f"Size={s.upper()}, State={st}",
                                          "componentSetId": "S:button", "remote": True}
              for s in ("l", "m", "s") for st in ("Default", "Pressed", "Disabled")}


def _ago(days: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))


def comments(pages) -> list[dict]:
    """Обсуждения по экранам: открытые, без ответа, давние, закрытые."""
    ids = {}
    for p in pages:
        for scr in p["children"]:
            ids[scr["name"]] = scr["id"]
    c, out = [0], []

    def add(screen_name, who, msg, days, resolved=None, replies=()):
        c[0] += 1
        cid = str(c[0])
        out.append({"id": cid, "message": msg, "user": {"handle": who}, "created_at": _ago(days),
                    "resolved_at": _ago(resolved) if resolved is not None else None,
                    "client_meta": {"node_id": ids[screen_name], "node_offset": {"x": 10, "y": 10}}})
        for j, (rw, rm, rd) in enumerate(replies):
            c[0] += 1
            out.append({"id": str(c[0]), "parent_id": cid, "message": rm, "user": {"handle": rw}, "created_at": _ago(rd)})
    add("Cart", "Alex", "The delivery hint is hard to read on white. Can we use Text/Secondary?", 3)
    add("Cart", "Sam", "Should the promo code field be a component?", 41)
    add("Payment", "Riley", "Pay button: do we show the total here or below?", 2,
        replies=[("Alex", "Total stays below, the button says Pay $178", 1.5), ("Riley", "Ok, then the summary card needs the total in bold", 1)])
    add("Payment / Success", "Sam", "Button on the dark sheet looks off. Inverse variant?", 5)
    add("Catalog", "Alex", "Cards: radius 13 on one of them, typo?", 20, resolved=19,
        replies=[("Sam", "Fixed, thanks", 19)])
    add("Catalog / Promo", "Riley", "Check the contrast of the subtitle on the gradient", 9)
    add("Delivery", "Sam", "Copy: 2–3 days or 2-3 business days?", 60, replies=[("Alex", "Waiting for legal", 55)])
    add("Profile", "Alex", "Sign out is a frame, not the Button component", 1)
    add("Settings", "Riley", "Disabled Save: do we need it at all?", 12, resolved=10)
    add("Catalog / Dark", "Sam", "Dark theme looks good", 8, resolved=8)
    return out


class DemoFigma:
    """Поддельная Figma для демо: те же запросы, что делает загрузчик."""

    def __init__(self, files: dict, version: str):
        self.files, self.version = files, version

    def file_meta(self, key):
        return {"name": NAMES[key], "version": self.version, "lastModified": _ago(0)}

    def file_head(self, key, depth=1):
        pages = []
        for p in self.files[key]:
            q = {k: v for k, v in p.items() if k != "children"}
            if depth >= 2:
                q["children"] = [{k: v for k, v in c.items() if k != "children"} for c in p["children"]]
            pages.append(q)
        return {"name": NAMES[key], "version": self.version, "lastModified": _ago(0),
                "document": {"id": "0:0", "type": "DOCUMENT", "children": pages}}

    def nodes(self, key, ids, depth=None):
        idx, stack = {}, list(self.files[key])
        while stack:
            n = stack.pop()
            idx[n["id"]] = n
            stack.extend(n.get("children") or [])
        res = {}
        for i in ids:
            n = copy.deepcopy(idx[i])
            if depth == 1:
                n["children"] = [{k: v for k, v in c.items() if k != "children"} for c in n.get("children") or []]
            res[i] = {"document": n, "styles": STYLES, "components": COMPONENTS,
                      "componentSets": {"S:button": {"key": "demo-button-set", "name": "Button"}}}
        return {"nodes": res}

    def get_json(self, path, params=None):
        if path.endswith("/comments") and f"/{APP}/" in path:
            return {"comments": comments(self.files[APP])}
        if path.endswith("/comments"):
            return {"comments": []}
        raise FigmaError("not_found", "Not available in the demo", 404)


def build(db_path: Path) -> Path:
    """Собирает демо-базу с нуля: проект, два файла, справочник, комментарии и три замера."""
    from . import comments as comments_mod
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    con = dbm.connect(db_path)
    try:
        with dbm.writing(con):
            con.execute("INSERT INTO projects (id, name, created_at) VALUES (1, 'Shop (demo)', ?)", (_ago(30),))
            for key in (APP, DS):
                con.execute("INSERT INTO sources (url, file_key, project_id, added_at) VALUES (?, ?, 1, ?)",
                            (f"https://www.figma.com/design/{key}/{NAMES[key].replace(' ', '-')}", key, _ago(30)))
        tokens.store(con, tokens.parse_all(json.dumps(library())), "demo-tokens.json", 1)
        # Три состояния файла: две недели назад, неделю назад и сейчас — для стрелок и графика.
        for stage, days in ((0, 14), (1, 7), (2, 0)):
            fig = DemoFigma({APP: app_pages(stage), DS: ds_pages()}, f"v{stage + 1}")
            for key in (APP, DS):
                load_file(con, fig, key, force=True)
            memo.clear()             # три состояния грузятся за одну секунду — подпись данных та же
            taken = health.snapshot(con, tokens.load(con, 1), 1)
            if taken and days:
                with dbm.writing(con):
                    con.execute("UPDATE snapshots SET taken_at = ? WHERE taken_at = ?", (_ago(days), taken))
            if stage == 2:
                for key in (APP, DS):
                    comments_mod.fetch(con, fig, key)
        with dbm.writing(con):
            con.execute("ANALYZE")
    finally:
        con.close()
    return db_path
