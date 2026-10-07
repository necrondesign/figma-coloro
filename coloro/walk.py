"""Дерево Figma → строки слоёв и строки цветов.

Обходится любое поддерево: страница целиком или отдельный слой, если страницу пришлось
скачивать по частям. Всё, что лежит выше поддерева, передаётся контекстом — скрыт ли кто-то
из родителей, путь секций, ближайший инстанс, — поэтому кусок, скачанный отдельно, получает
те же метки, что получил бы в составе страницы.

Ничего не отбрасывается. Скрытый слой, безымянная фигура, слой в архивной секции — всё
записывается с метками, а учитывать или нет, решают фильтры при просмотре.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .textnorm import norm


# Что считается экраном: самый внешний кадр под страницей. Секции и группы — это
# контейнеры, в которых экраны лежат, сами они экранами не считаются.
SCREEN_TYPES = ("FRAME", "COMPONENT", "COMPONENT_SET", "INSTANCE")


def plain_id(nid: str) -> bool:
    """Обычный id слоя, на который ведёт ссылка Figma. У слоёв внутри инстанса id составной
    (I4041:9063;3233:43784), и ссылка на такой слой не открывается."""
    return bool(nid) and ";" not in nid and not nid.startswith("I")


@dataclass
class Ctx:
    file_key: str
    page_id: str
    parent_id: str | None = None
    hidden: bool = False                       # скрыт кто-то из родителей
    sections: tuple[str, ...] = ()             # секции над поддеревом, снаружи внутрь
    pinst: str | None = None                   # ближайший родитель-инстанс
    screen: str | None = None                  # экран, в который входит поддерево
    anchor: str | None = None                  # ближайший предок, на которого ведёт ссылка


@dataclass
class Out:
    nodes: list[tuple] = field(default_factory=list)
    paints: list[tuple] = field(default_factory=list)
    components: dict = field(default_factory=dict)
    props: list[tuple] = field(default_factory=list)     # отступы, скругления, толщина обводки
    effects: list[tuple] = field(default_factory=list)   # тени и размытия
    images: list[tuple] = field(default_factory=list)    # картинки в заливках


def _hex(c: dict) -> str:
    return "%02X%02X%02X" % tuple(max(0, min(255, int(round((c.get(k) or 0) * 255)))) for k in ("r", "g", "b"))


def _pct(v) -> int:
    try:
        return max(0, min(100, int(round(float(v) * 100))))
    except (TypeError, ValueError):
        return 100


def _tenths(v):
    return int(round(v * 10)) if isinstance(v, (int, float)) else None


def _num(v) -> str:
    return f"{round(v, 2):g}" if isinstance(v, (int, float)) else ""


def _style_name(styles: dict, sid) -> str:
    return ((styles.get(sid) or {}).get("name") or "Untitled") if sid else ""


# Какие ключи в node.styles говорят о стиле ЦВЕТА у заливки и у обводки.
# Ключ «text» — это стиль типографики (шрифт, кегль), к цвету он отношения не имеет:
# текст со стилем шрифта и вручную набранным цветом — это цвет, набранный вручную.
_STYLE_KEYS = {"fills": ("fill", "fills"), "strokes": ("stroke", "strokes")}
_SLOT = {"fills": "fill", "strokes": "stroke"}


def paints_of(node: dict, styles: dict, intern) -> list[tuple]:
    """Все видимые краски слоя → (slot, kind, color, alpha, src, grad)."""
    out: list[tuple] = []
    st = node.get("styles") or {}
    bv = node.get("boundVariables") or {}
    for field_name, keys in _STYLE_KEYS.items():
        paints = node.get(field_name)
        if not isinstance(paints, list) or not paints:
            continue
        sid = next((st[k] for k in keys if st.get(k)), None)
        style_src = "s:" + _style_name(styles, sid) if sid else None
        bvlist = bv.get(field_name) or []
        slot = _SLOT[field_name]
        for i, p in enumerate(paints):
            if not isinstance(p, dict) or p.get("visible") is False:
                continue
            t = p.get("type") or ""
            if t == "SOLID":
                c = p.get("color") or {}
                # Переменная бывает привязана и на слое (boundVariables.fills[i]),
                # и на самой краске (paint.boundVariables.color) — считаются обе.
                var = (i < len(bvlist) and bvlist[i]) or (p.get("boundVariables") or {}).get("color")
                a = (c.get("a") if c.get("a") is not None else 1) * (p.get("opacity") if p.get("opacity") is not None else 1)
                out.append((slot, "solid", _hex(c), _pct(a), style_src or ("v" if var else None), None))
            elif t.startswith("GRADIENT"):
                stops = [s for s in p.get("gradientStops") or [] if isinstance(s, dict) and s.get("color")]
                if not stops:
                    continue
                # Рецепт — вид градиента и его стопы по порядку. По нему одинаковые
                # градиенты собираются вместе, а разные — нет.
                recipe = t + ":" + "→".join(f"{_hex(s['color'])}@{_pct(s['color'].get('a', 1))}" for s in stops)
                gid = intern(recipe)
                seen = set()
                for s in stops:
                    c = s["color"]
                    # Два одинаковых стопа в одном градиенте — одно применение цвета.
                    key = (_hex(c), _pct(c.get("a", 1)))
                    if key in seen:
                        continue
                    seen.add(key)
                    var = (s.get("boundVariables") or {}).get("color")
                    # У стопа — только его собственная прозрачность. Прозрачность краски
                    # целиком к цвету стопа не относится.
                    out.append((slot, "stop", _hex(c), _pct(c.get("a", 1)), style_src or ("v" if var else None), gid))
    return out


def _px(v):
    return round(float(v), 2) if isinstance(v, (int, float)) else None


def props_of(node: dict) -> list[tuple]:
    """Числа, у которых в дизайн-системе обычно есть шкала: отступы, скругления, обводка.

    → (вид, величина, привязана ли к переменной). Нули не пишутся: отсутствие отступа —
    это не отступ мимо шкалы."""
    out = []
    bv = node.get("boundVariables") or {}
    if node.get("layoutMode") in ("HORIZONTAL", "VERTICAL"):
        # При «Space between» промежуток считает сама Figma, записанное число не применяется.
        if node.get("primaryAxisAlignItems") != "SPACE_BETWEEN":
            out.append(("gap", _px(node.get("itemSpacing")), bool(bv.get("itemSpacing"))))
        if node.get("layoutWrap") == "WRAP" and node.get("counterAxisAlignContent") != "SPACE_BETWEEN":
            out.append(("gap", _px(node.get("counterAxisSpacing")), bool(bv.get("counterAxisSpacing"))))
        for side in ("Top", "Right", "Bottom", "Left"):
            out.append(("padding", _px(node.get("padding" + side)), bool(bv.get("padding" + side))))
    radii = node.get("rectangleCornerRadii")
    corner_keys = ("topLeftRadius", "topRightRadius", "bottomRightRadius", "bottomLeftRadius")
    if isinstance(radii, list) and len(radii) == 4 and len(set(radii)) > 1:
        for k, r in zip(corner_keys, radii):
            out.append(("radius", _px(r), bool(bv.get(k))))
    elif isinstance(node.get("cornerRadius"), (int, float)):
        out.append(("radius", _px(node["cornerRadius"]), any(bv.get(k) for k in corner_keys + ("cornerRadius",))))
    strokes = node.get("strokes")
    if isinstance(strokes, list) and any(isinstance(p, dict) and p.get("visible") is not False for p in strokes):
        out.append(("stroke", _px(node.get("strokeWeight")), bool(bv.get("strokeWeight"))))
    return [p for p in out if p[1]]


def effects_of(node: dict, styles: dict) -> list[tuple]:
    """Тени и размытия → (вид, цвет, прозрачность, x, y, размытие, разлёт, источник)."""
    out = []
    sid = (node.get("styles") or {}).get("effect")
    style_src = "s:" + _style_name(styles, sid) if sid else None
    for e in node.get("effects") or []:
        if not isinstance(e, dict) or e.get("visible") is False:
            continue
        c = e.get("color")
        off = e.get("offset") or {}
        var = (e.get("boundVariables") or {}).get("color")
        out.append((e.get("type") or "", _hex(c) if c else None, _pct(c.get("a", 1)) if c else None,
                    _px(off.get("x")), _px(off.get("y")), _px(e.get("radius")), _px(e.get("spread")),
                    style_src or ("v" if var else None)))
    return out


def images_of(node: dict) -> list[tuple]:
    out = []
    for p in node.get("fills") or []:
        if isinstance(p, dict) and p.get("type") == "IMAGE" and p.get("visible") is not False:
            out.append((p.get("imageRef") or "", p.get("scaleMode") or ""))
    return out


def _font(node: dict) -> str | None:
    t = node.get("style") or {}
    if not t:
        return None
    return ";".join([
        t.get("fontFamily") or "",
        t.get("fontStyle") or ("Italic" if t.get("italic") else ""),
        _num(t.get("fontWeight")), _num(t.get("fontSize")),
        _num(t.get("lineHeightPx")), _num(t.get("letterSpacing")),
    ])


def walk(root: dict, ctx: Ctx, styles: dict, intern, first_seen: dict, now: str,
         out: Out, children: bool = True) -> None:
    """Обходит поддерево и дописывает строки в out.

    children=False — записать только сам узел: его детей загрузчик скачает отдельно.
    """
    stack = [(root, ctx.parent_id, ctx.hidden, ctx.sections, ctx.pinst, ctx.screen, ctx.anchor)]
    while stack:
        node, parent, hidden_above, sections, pinst, screen, anchor = stack.pop()
        nid = node.get("id") or ""
        ntype = node.get("type") or ""
        name = node.get("name") or ""
        hidden = hidden_above or node.get("visible") is False
        if screen is None and ntype in SCREEN_TYPES:
            screen = nid
        if plain_id(nid):
            anchor = nid
        box = node.get("absoluteBoundingBox") or {}
        st = node.get("styles") or {}
        is_text = ntype == "TEXT"
        out.nodes.append((
            ctx.file_key, ctx.page_id, nid, parent, ntype, name,
            1 if hidden else 0,
            intern(" / ".join(sections)) if sections else None,
            pinst,
            node.get("componentId") if ntype == "INSTANCE" else None,
            node.get("characters") if is_text else None,
            _tenths(box.get("x")), _tenths(box.get("y")), _tenths(box.get("width")), _tenths(box.get("height")),
            intern(_font(node)) if is_text else None,
            intern(_style_name(styles, st.get("text"))) if is_text and st.get("text") else None,
            first_seen.get(nid) or now,
            screen, anchor,
            (1 if node.get("overrides") else 0) if ntype == "INSTANCE" else None,
            norm(node.get("characters")) if is_text else None,
            norm(name),
        ))
        row = out.nodes[-1]
        # Поля фильтров — прямо у краски: тогда цвета считаются без обращения к слоям,
        # а это на миллионах слоёв разница в разы.
        tail = (row[6], 1 if pinst else 0, row[7], screen, row[17])
        for p in paints_of(node, styles, intern):
            out.paints.append((ctx.file_key, ctx.page_id, nid, *p, *tail))
        # Отступы и эффекты сверяются только у положенного на экран вручную: внутри компонента
        # их задаёт библиотека. Хранить их там — 93% строк впустую.
        if pinst is None and ntype != "INSTANCE":
            for p in props_of(node):
                out.props.append((ctx.file_key, ctx.page_id, nid, *p))
            for e in effects_of(node, styles):
                out.effects.append((ctx.file_key, ctx.page_id, nid, *e))
        for im in images_of(node):
            out.images.append((ctx.file_key, ctx.page_id, nid, *im))
        if not children and node is root:
            continue
        kids = node.get("children") or []
        if kids:
            child_sections = sections + (name,) if ntype == "SECTION" else sections
            child_pinst = nid if ntype == "INSTANCE" else pinst
            for kid in reversed(kids):
                stack.append((kid, nid, hidden, child_sections, child_pinst, screen, anchor))


def child_ctx(node: dict, ctx: Ctx) -> Ctx:
    """Контекст для детей узла, когда дети скачиваются отдельно от него."""
    ntype = node.get("type") or ""
    nid = node.get("id") or ""
    return Ctx(
        file_key=ctx.file_key, page_id=ctx.page_id, parent_id=nid,
        hidden=ctx.hidden or node.get("visible") is False,
        sections=ctx.sections + ((node.get("name") or ""),) if ntype == "SECTION" else ctx.sections,
        pinst=nid if ntype == "INSTANCE" else ctx.pinst,
        screen=ctx.screen or (nid if ntype in SCREEN_TYPES else None),
        anchor=nid if plain_id(nid) else ctx.anchor,
    )
