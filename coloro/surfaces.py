"""Поверхности: что на чём лежит.

Поверхность слоя считается при загрузке (walk.surface_of): заливка ближайшего родителя или
подложки под слоем, полупрозрачное смешано с тем, что ниже. Отсюда три ответа:

  поверхности — какие фоны есть в макетах и что на каждом стоит: тексты каких цветов, какие
               компоненты;
  контраст    — цвет текста против его фона по WCAG 2: нечитаемое видно сразу. Крупный текст
               (от 24 px, или от 18,66 px жирный) требует 3:1, обычный — 4,5:1 (AA), 7:1 — AAA;
  компоненты  — на каких фонах стоит каждый компонент. Если компонент почти всегда на светлом,
               а в нескольких местах на тёмном, — скорее всего, там нужен другой вариант.

Текст на картинке, градиенте или на краю подложки (часть букв на ней, часть — нет) честно не
проверяется: контраст там зависит от места.
"""

from __future__ import annotations

from .filters import NODE_SCAN, Filter
from .typography import parse as font_parse

AA, AA_LARGE, AAA, AAA_LARGE = 4.5, 3.0, 7.0, 4.5
UNUSUAL_SHARE = 0.1          # меньше такой доли мест на фоне этого тона — необычное место
UNUSUAL_MIN_USES = 10        # у компонента должно быть хотя бы столько мест, чтобы судить
TOP = 12
MAX_ON = 200                 # сколько компонентов показывать на одной поверхности


def parse(key: str | None) -> dict:
    """«RRGGBB@50|s:Стиль» → вид, цвет, прозрачность, источник."""
    if not key:
        return {"kind": "none", "color": None, "alpha": None, "src": None}
    if key in ("image", "gradient", "mixed"):
        return {"kind": key, "color": None, "alpha": None, "src": None}
    value, _, src = key.partition("|")
    color, _, alpha = value.partition("@")
    return {"kind": "solid", "color": color, "alpha": int(alpha) if alpha else 100, "src": src or None}


def _lin(c: int) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexv: str) -> float:
    r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def blend(top: str, alpha: int, base: str) -> str:
    a = alpha / 100
    t = [int(top[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(base[i:i + 2], 16) for i in (0, 2, 4)]
    return "%02X%02X%02X" % tuple(int(round(x * a + y * (1 - a))) for x, y in zip(t, b))


def tone(s: dict) -> str:
    """Светлый или тёмный фон — граница там, где белый и чёрный текст читаются одинаково."""
    if s["kind"] != "solid":
        return s["kind"]
    return "dark" if luminance(s["color"]) < 0.18 else "light"


def is_large(font: dict) -> bool:
    size, weight = font.get("size") or 0, font.get("weight") or 400
    return size >= 24 or (size >= 18.66 and weight >= 700)


_FG_WORDS = ("text", "fg", "foreground", "label", "content", "icon", "on ")
_BG_WORDS = ("surface", "background", "bg", "fill", "container", "base", "layer")


def _prefer(names: list[str], words) -> list[str]:
    """У одного значения бывает несколько токенов (белый — и фон, и текст на акценте). Для текста
    первыми — текстовые токены, для фона — токены поверхностей."""
    return sorted(names, key=lambda n: (not any(w in n.lower() for w in words), n))


def _name(s: dict, idx) -> str:
    if s["kind"] == "image":
        return "Image"
    if s["kind"] == "gradient":
        return "Gradient"
    if s["kind"] == "mixed":
        return "Partly on a plate"
    if s["kind"] == "none":
        return "No background"
    if s["src"] and s["src"].startswith("s:"):
        return s["src"][2:]
    toks = _prefer(idx.exact(s["color"], s["alpha"]), _BG_WORDS) if idx else []
    return toks[0] if toks else "#" + s["color"] + (f" {s['alpha']}%" if s["alpha"] < 100 else "")


def report(con, filt: Filter, idx) -> dict:
    where, args = filt.where()
    vals: dict[int, str] = {}

    def val(i):
        if i not in vals:
            got = con.execute("SELECT v FROM vals WHERE id = ?", (i,)).fetchone() if i else None
            vals[i] = got[0] if got else None
        return vals[i]

    # Тексты: цвет букв против фона — оба записаны у слоя при загрузке, один проход по слоям.
    pairs: dict[tuple, dict] = {}
    for bg, fg, fid, uses, screens, files in con.execute(
            "SELECT n.bg, n.fg, n.font, COUNT(*), COUNT(DISTINCT n.file_key || '|' || IFNULL(n.screen, '')),"
            " COUNT(DISTINCT n.file_key) FROM nodes n" + NODE_SCAN +
            f" WHERE n.type = 'TEXT' AND n.fg IS NOT NULL AND {where} GROUP BY n.bg, n.fg, n.font", args):
        raw = val(fg) or "000000@100"
        fill, _, stroke = raw.partition("~")
        c, _, a = fill.partition("@")
        if int(a or 100) < 5:
            continue                                   # невидимый текст
        k = (bg, c, int(a or 100), stroke or None, is_large(font_parse(val(fid))), raw)
        x = pairs.setdefault(k, {"uses": 0, "screens": 0, "files": 0})
        x["uses"] += uses
        x["screens"] = max(x["screens"], screens)
        x["files"] = max(x["files"], files)

    contrast = []
    for (bg, c, a, stroke, big, raw), x in pairs.items():
        s = parse(val(bg))
        item = {"bg": bg, "surface": _name(s, idx), "bg_kind": s["kind"], "bg_color": s["color"], "fg": raw,
                "color": c, "alpha": a, "outline": stroke, "fg_tokens": _prefer(idx.exact(c, a), _FG_WORDS) if idx else [], "large": big, **x}
        if s["kind"] != "solid" or s["alpha"] < 100:
            # Картинка, градиент или полупрозрачный фон, под которым ничего не нашлось.
            item.update(status="unknown", ratio=None, need=None)
        else:
            fg = blend(c, a, s["color"]) if a < 100 else c
            r = max(ratio(fg, s["color"]), ratio(stroke, s["color"]) if stroke else 0)
            need, best = (AA_LARGE, AAA_LARGE) if big else (AA, AAA)
            item.update(ratio=r, need=need, effective=fg,
                        status="fail" if r < need else "aa" if r < best else "aaa")
        contrast.append(item)
    # Сначала то, что чаще встречается: исправление одной пары чинит сразу много мест.
    contrast.sort(key=lambda i: ({"fail": 0, "unknown": 1, "aa": 2, "aaa": 3}[i["status"]], -i["uses"], i["ratio"] or 0))

    # Компоненты, положенные на экран: на каком фоне стоит каждый.
    names = {}
    for fk, cid, name, sname in con.execute("SELECT file_key, id, name, set_name FROM components"):
        names[(fk, cid)] = ("set", sname) if sname else ("cname", name or "Untitled")
    comps: dict[tuple, dict] = {}
    on_surface: dict[int, dict] = {}
    for bg, fk, cid, uses, screens, files in con.execute(
            "SELECT n.bg, n.file_key, n.comp, COUNT(*), COUNT(DISTINCT n.file_key || '|' || IFNULL(n.screen, '')),"
            " COUNT(DISTINCT n.file_key) FROM nodes n" + NODE_SCAN +
            f" WHERE n.type = 'INSTANCE' AND n.pinst IS NULL AND {where} GROUP BY n.bg, n.file_key, n.comp", args):
        key = names.get((fk, cid), ("cname", "Untitled"))
        g = comps.setdefault(key, {"kind": key[0], "name": key[1], "uses": 0, "screens": 0, "files": 0,
                                   "tones": {}, "bgs": {}})
        g["uses"] += uses
        g["screens"] += screens
        g["files"] = max(g["files"], files)
        t = tone(parse(val(bg)))
        g["tones"][t] = g["tones"].get(t, 0) + uses
        g["bgs"].setdefault(t, set()).add(bg)
        g.setdefault("on", {})
        g["on"][bg] = g["on"].get(bg, 0) + uses
        on = on_surface.setdefault(bg, {})
        on[key] = on.get(key, 0) + uses

    components = []
    for g in comps.values():
        unusual = []
        if g["uses"] >= UNUSUAL_MIN_USES:
            main = max(g["tones"], key=g["tones"].get)
            for t, n in g["tones"].items():
                if t != main and t in ("light", "dark") and main in ("light", "dark") and n / g["uses"] < UNUSUAL_SHARE:
                    unusual.append({"tone": t, "uses": n, "bgs": sorted(b for b in g["bgs"][t] if b)})
        on = []
        for bg, n in sorted(g.get("on", {}).items(), key=lambda kv: -kv[1])[:40]:
            p = parse(val(bg))
            on.append({"bg": bg, "name": _name(p, idx), "kind": p["kind"], "color": p["color"], "alpha": p["alpha"],
                       "tone": tone(p), "uses": n})
        components.append({"kind": g["kind"], "name": g["name"], "uses": g["uses"], "screens": g["screens"],
                           "files": g["files"], "tones": g["tones"], "unusual": unusual, "on": on,
                           "unusual_uses": sum(u["uses"] for u in unusual)})
    components.sort(key=lambda g: (-g["unusual_uses"], -g["uses"], g["name"]))

    # Поверхности: что на каждой стоит.
    surfaces: dict[int, dict] = {}
    for i in contrast:
        s = surfaces.setdefault(i["bg"], {"texts": 0, "fail": 0, "colors": {}, "screens": 0})
        s["texts"] += i["uses"]
        s["screens"] = max(s["screens"], i["screens"])
        if i["status"] == "fail":
            s["fail"] += i["uses"]
        s["colors"][(i["color"], i["alpha"])] = s["colors"].get((i["color"], i["alpha"]), 0) + i["uses"]
    for bg, on in on_surface.items():
        surfaces.setdefault(bg, {"texts": 0, "fail": 0, "colors": {}, "screens": 0})
    out = []
    for bg, s in surfaces.items():
        p = parse(val(bg))
        on = on_surface.get(bg, {})
        out.append({"bg": bg, "name": _name(p, idx), "kind": p["kind"], "color": p["color"], "alpha": p["alpha"],
                    "src": p["src"], "tone": tone(p), "tokens": idx.exact(p["color"], p["alpha"]) if idx and p["color"] else [],
                    "texts": s["texts"], "fail": s["fail"], "components": sum(on.values()),
                    "uses": s["texts"] + sum(on.values()), "screens": s["screens"],
                    "text_colors": [{"color": c, "alpha": a, "uses": n} for (c, a), n in
                                    sorted(s["colors"].items(), key=lambda kv: -kv[1])[:TOP]],
                    "top_components": [{"kind": k[0], "name": k[1], "uses": n} for k, n in
                                       sorted(on.items(), key=lambda kv: -kv[1])[:MAX_ON]]})
    out.sort(key=lambda s: (-s["uses"], s["name"]))

    def total(st):
        return sum(i["uses"] for i in contrast if st is None or i["status"] == st)
    return {"surfaces": out, "contrast": contrast, "components": components,
            "totals": {"texts": total(None), "fail": total("fail"), "unknown": total("unknown"),
                       "aa": total("aa"), "aaa": total("aaa"), "surfaces": len(out),
                       "unusual": sum(g["unusual_uses"] for g in components),
                       "placed": sum(g["uses"] for g in components)}}


def condition(q: dict, con=None) -> tuple[str, list]:
    """Места на поверхности: что угодно на ней, тексты одного цвета или один компонент."""
    def one(k):
        v = q.get(k)
        return v[0] if isinstance(v, list) else v
    bgs = [int(x) for x in str(one("bgs") or one("bg") or "").split(",") if x.strip().lstrip("-").isdigit()]
    parts, args = [], []
    if bgs:
        parts.append(f"n.bg IN ({','.join('?' * len(bgs))})")
        args += bgs
    elif one("bg") == "none":
        parts.append("n.bg IS NULL")
    what = one("what") or ""
    if what == "text":
        parts.append("n.type = 'TEXT'")
        if one("fg") or one("color"):
            parts.append("n.fg = (SELECT id FROM vals WHERE v = ?)")
            args.append(one("fg") or f"{str(one('color')).upper()}@{int(one('alpha') or 100)}")
    elif what == "component":
        from .search import condition as search_condition
        c, a, _ = search_condition("component", {k: one(k) for k in ("set", "cname") if one(k)}, con)
        parts.append(f"n.pinst IS NULL AND {c}")
        args += a
    else:
        parts.append("(n.type = 'TEXT' OR (n.type = 'INSTANCE' AND n.pinst IS NULL))")
    return " AND ".join(parts), args
