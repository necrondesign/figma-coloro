"""Типографика: тексты без стиля против системы стилей.

Система стилей не загружается отдельно — она выводится из самих макетов. Тексты, у которых
назначен текстовый стиль, показывают, какие сочетания «шрифт, начертание, кегль,
интерлиньяж» в дизайн-системе приняты. Каждый текст без стиля сравнивается с ними:

  unbound — сочетание точно как у стиля, но стиль не назначен → назначить стиль
  near    — тот же шрифт и вес, кегль или интерлиньяж чуть другие → заменить на стиль
  off     — такого сочетания в системе нет → решить, нужен ли новый стиль

Считаются только тексты, положенные на экран вручную: внутри компонента типографику задаёт
библиотека, и на экране её не исправить.
"""

from __future__ import annotations

from .filters import NODE_JOIN, Filter

NEAR_SIZE = 1.0      # насколько может отличаться кегль у «почти стиля», px
NEAR_LINE = 2.0      # и интерлиньяж, px

# Пока шрифт не загружен на компьютере, его вес по числу всё равно понятен.
_WEIGHT_NAMES = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium",
                 600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black"}


def parse(spec: str | None) -> dict:
    """«Inter;Semi Bold;600;16;24;0» → поля. Пустые числа — None."""
    parts = (spec or "").split(";") + [""] * 6
    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    return {"family": parts[0], "style": parts[1], "weight": num(parts[2]), "size": num(parts[3]),
            "line": num(parts[4]), "tracking": num(parts[5])}


def _n(v) -> str:
    return "—" if v is None else f"{v:g}"


def label(f: dict) -> str:
    """«Inter SemiBold 16/24» — так, как дизайнер называет шрифт вслух."""
    style = f["style"] or _WEIGHT_NAMES.get(int(f["weight"] or 0), "")
    size = _n(f["size"]) + (f"/{_n(f['line'])}" if f["line"] else "")
    return " ".join(x for x in (f["family"], style, size) if x)


def _same_face(a: dict, b: dict) -> bool:
    return a["family"] == b["family"] and (a["weight"] == b["weight"] or a["style"] == b["style"])


def catalog(con) -> list[dict]:
    """Стили, которые реально используются, и их самое частое сочетание шрифта.

    Берутся все тексты со стилем, в том числе внутри компонентов: компоненты библиотеки —
    лучший образец того, как стиль задуман."""
    rows = con.execute(
        "SELECT sv.v, fv.v, COUNT(*) FROM nodes n"
        " JOIN vals sv ON sv.id = n.tstyle JOIN vals fv ON fv.id = n.font"
        " WHERE n.type = 'TEXT' AND n.tstyle IS NOT NULL AND n.font IS NOT NULL"
        " GROUP BY sv.v, fv.v ORDER BY 3 DESC").fetchall()
    best: dict[str, tuple] = {}
    for name, spec, uses in rows:
        if name not in best:
            best[name] = (spec, uses)
    out = []
    for name, (spec, uses) in best.items():
        f = parse(spec)
        out.append({"name": name, "spec": spec, "label": label(f), "font": f, "uses": uses})
    out.sort(key=lambda s: (s["font"]["size"] or 0, s["name"]), reverse=True)
    return out


def classify(f: dict, styles: list[dict], spec: str) -> dict:
    exact = [s["name"] for s in styles if s["spec"] == spec]
    if exact:
        return {"status": "unbound", "styles": exact, "nearest": None}
    best, best_d = None, None
    for s in styles:
        g = s["font"]
        if not _same_face(f, g) or f["size"] is None or g["size"] is None:
            continue
        d = abs(f["size"] - g["size"]) * 4 + abs((f["line"] or 0) - (g["line"] or 0))
        if best is None or d < best_d:
            best, best_d = s, d
    nearest = None
    if best:
        g = best["font"]
        nearest = {"name": best["name"], "label": best["label"],
                   "dsize": round((f["size"] or 0) - (g["size"] or 0), 2),
                   "dline": round((f["line"] or 0) - (g["line"] or 0), 2)}
        if abs(nearest["dsize"]) <= NEAR_SIZE and abs(nearest["dline"]) <= NEAR_LINE:
            return {"status": "near", "styles": [], "nearest": nearest}
    # Почему мимо: шрифта нет в системе вовсе (Inter в системе на Ubuntu) или нет только
    # этого начертания (Ubuntu Medium, когда в системе Regular и Bold). Это разные решения.
    family_known = any(s["font"]["family"] == f["family"] for s in styles)
    return {"status": "off", "styles": [], "nearest": nearest, "family_known": family_known}


def fonts(con, filt: Filter) -> dict:
    """Сочетания шрифта у текстов без стиля, положенных на экран вручную, — со статусом."""
    where, args = filt.where()
    styles = catalog(con)
    rows = con.execute(
        "SELECT n.font, fv.v, COUNT(*), COUNT(DISTINCT n.file_key || '|' || IFNULL(n.screen, '')),"
        " COUNT(DISTINCT n.file_key), MIN(n.first_seen)"
        " FROM nodes n" + NODE_JOIN + " JOIN vals fv ON fv.id = n.font"
        f" WHERE {where} AND n.type = 'TEXT' AND n.pinst IS NULL AND n.tstyle IS NULL"
        " GROUP BY n.font ORDER BY 3 DESC", args).fetchall()
    items = []
    for fid, spec, uses, screens, files, first in rows:
        f = parse(spec)
        item = {"font_id": fid, "spec": spec, "label": label(f), "font": f, "uses": uses,
                "screens": screens, "files": files, "first_seen": first, "rare": uses <= 2}
        item.update(classify(f, styles, spec))
        items.append(item)
    sizes: dict[float, dict] = {}
    for s in styles:
        if s["font"]["size"] is not None:
            sizes.setdefault(s["font"]["size"], {"size": s["font"]["size"], "styles": 0, "loose": 0})["styles"] += 1
    for i in items:
        if i["font"]["size"] is not None:
            sizes.setdefault(i["font"]["size"], {"size": i["font"]["size"], "styles": 0, "loose": 0})["loose"] += i["uses"]
    return {"styles": styles, "items": items,
            "sizes": sorted(sizes.values(), key=lambda x: x["size"])}
