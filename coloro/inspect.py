"""Разметка компонента для разработки: рамки слоёв, поля, промежутки и свойства.

Картинку компонента рисует сама Figma — она точная. Поверх неё интерфейс рисует разметку из
этих данных: координаты каждого слоя относительно картинки, auto layout, скругления, цвета с
токенами проекта, тени, текст. Всё — числа из Figma, ничего не угадывается.

Координаты считаются от границ отрисовки корня (absoluteRenderBounds): Figma рисует картинку
вместе с тенями, и только так рамки слоёв ложатся на картинку точно.
"""

from __future__ import annotations

from .effects import label as effect_label
from .tokens import Index
from .walk import _hex, _pct

MAX_LAYERS = 600
SIZING = {"FIXED": "fixed", "HUG": "hug", "FILL": "fill"}
ALIGN = {"MIN": "start", "CENTER": "center", "MAX": "end", "SPACE_BETWEEN": "space between", "BASELINE": "baseline"}


def _num(v):
    return round(float(v), 2) if isinstance(v, (int, float)) else None


def _paints(paints, idx: Index, style: str | None, bound: list) -> list[dict]:
    out = []
    for i, p in enumerate(paints or []):
        if not isinstance(p, dict) or p.get("visible") is False:
            continue
        t = p.get("type") or ""
        var = (i < len(bound) and bound[i]) or (p.get("boundVariables") or {}).get("color")
        if t == "SOLID":
            c = p.get("color") or {}
            a = (c.get("a") if c.get("a") is not None else 1) * (p.get("opacity") if p.get("opacity") is not None else 1)
            hexv, alpha = _hex(c), _pct(a)
            out.append({"kind": "solid", "color": hexv, "alpha": alpha, "style": style,
                        "variable": bool(var), "tokens": idx.exact(hexv, alpha) if idx else []})
        elif t.startswith("GRADIENT"):
            stops = [{"color": _hex(s["color"]), "alpha": _pct(s["color"].get("a", 1))}
                     for s in p.get("gradientStops") or [] if isinstance(s, dict) and s.get("color")]
            out.append({"kind": t.replace("GRADIENT_", "").lower() + " gradient", "stops": stops, "style": style})
        elif t == "IMAGE":
            out.append({"kind": "image", "mode": (p.get("scaleMode") or "").lower(), "style": style})
    return out


def build(entry: dict, idx: Index) -> dict:
    """Ответ Figma /nodes для одного слоя → дерево разметки (плоский список с родителями)."""
    root = entry["document"]
    styles = entry.get("styles") or {}
    rb = root.get("absoluteRenderBounds") or root.get("absoluteBoundingBox") or {}
    ox, oy = rb.get("x") or 0, rb.get("y") or 0
    items: list[dict] = []

    def style_name(n, key):
        sid = (n.get("styles") or {}).get(key)
        return (styles.get(sid) or {}).get("name") if sid else None

    def walk(n, parent):
        if len(items) >= MAX_LAYERS or n.get("visible") is False:
            return
        bb = n.get("absoluteBoundingBox") or {}
        if bb.get("width") is None:
            return
        bv = n.get("boundVariables") or {}
        it = {"i": len(items), "p": parent, "id": n.get("id"), "name": n.get("name") or "", "type": n.get("type") or "",
              "x": _num((bb.get("x") or 0) - ox), "y": _num((bb.get("y") or 0) - oy),
              "w": _num(bb.get("width")), "h": _num(bb.get("height")),
              "bound": sorted(k for k in bv.keys() if k not in ("fills", "strokes"))}
        if n.get("layoutSizingHorizontal") or n.get("layoutSizingVertical"):
            it["sizing"] = [SIZING.get(n.get("layoutSizingHorizontal"), ""), SIZING.get(n.get("layoutSizingVertical"), "")]
        if n.get("layoutMode") in ("HORIZONTAL", "VERTICAL"):
            between = n.get("primaryAxisAlignItems") == "SPACE_BETWEEN"
            it["layout"] = {
                "dir": "row" if n["layoutMode"] == "HORIZONTAL" else "column",
                "gap": "auto" if between else _num(n.get("itemSpacing") or 0),
                "pad": [_num(n.get("padding" + s) or 0) for s in ("Top", "Right", "Bottom", "Left")],
                "main": ALIGN.get(n.get("primaryAxisAlignItems") or "MIN", ""),
                "cross": ALIGN.get(n.get("counterAxisAlignItems") or "MIN", ""),
                "wrap": n.get("layoutWrap") == "WRAP",
            }
        radii = n.get("rectangleCornerRadii")
        if isinstance(radii, list) and len(radii) == 4 and len(set(radii)) > 1:
            it["radius"] = [_num(r) for r in radii]
        elif n.get("cornerRadius"):
            it["radius"] = _num(n["cornerRadius"])
        fills = _paints(n.get("fills"), idx, style_name(n, "fill") or style_name(n, "fills"), bv.get("fills") or [])
        if fills:
            it["fills"] = fills
        strokes = _paints(n.get("strokes"), idx, style_name(n, "stroke") or style_name(n, "strokes"), bv.get("strokes") or [])
        if strokes:
            it["strokes"] = strokes
            it["stroke_weight"] = _num(n.get("strokeWeight"))
            it["stroke_align"] = (n.get("strokeAlign") or "").lower()
        fx = [e for e in n.get("effects") or [] if isinstance(e, dict) and e.get("visible") is not False]
        if fx:
            it["effects"] = [{"label": effect_label({"type": e.get("type") or "", "x": (e.get("offset") or {}).get("x"),
                                                     "y": (e.get("offset") or {}).get("y"), "radius": e.get("radius"),
                                                     "spread": e.get("spread")}),
                              "color": _hex(e["color"]) if e.get("color") else None,
                              "alpha": _pct(e["color"].get("a", 1)) if e.get("color") else None} for e in fx]
            it["effect_style"] = style_name(n, "effect")
        if n.get("opacity") is not None and n.get("opacity") < 1:
            it["opacity"] = _pct(n["opacity"])
        if it["type"] == "TEXT":
            st = n.get("style") or {}
            it["text"] = {"chars": (n.get("characters") or "")[:200], "family": st.get("fontFamily"),
                          "style": st.get("fontStyle"), "weight": st.get("fontWeight"), "size": _num(st.get("fontSize")),
                          "line": _num(st.get("lineHeightPx")), "tracking": _num(st.get("letterSpacing")),
                          "align": (st.get("textAlignHorizontal") or "").lower(), "style_name": style_name(n, "text")}
        if it["type"] == "INSTANCE":
            it["component"] = n.get("componentId")
        items.append(it)
        if it["type"] in ("VECTOR", "BOOLEAN_OPERATION", "STAR", "LINE", "ELLIPSE", "POLYGON", "REGULAR_POLYGON"):
            return                                   # внутри фигур слоёв для разработки нет
        for k in n.get("children") or []:
            walk(k, it["i"])

    walk(root, None)
    return {"width": _num(rb.get("width")), "height": _num(rb.get("height")), "layers": items,
            "capped": len(items) >= MAX_LAYERS}
