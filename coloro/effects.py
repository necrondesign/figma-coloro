"""Тени, размытия и картинки.

Эффекты сравниваются со стилями эффектов так же, как тексты с текстовыми стилями: система
выводится из макетов — каждое сочетание параметров, встреченное в стиле, считается принятым.
Эффект, набранный вручную, получает статус:

  unbound — параметры точно как в стиле, но стиль не назначен → назначить стиль
  near    — тот же вид и цвет, смещение и размытие чуть другие → заменить на стиль
  off     — такого эффекта в системе нет

Картинки — это учёт: какие изображения где стоят и сколько раз, чтобы найти дубли, забытые
заглушки и тяжёлые места.
"""

from __future__ import annotations

from . import color as colorm
from .filters import NODE_JOIN, Filter

MANUAL = "n.pinst IS NULL AND n.type != 'INSTANCE'"
NEAR_OFFSET = 1.0
NEAR_RADIUS = 2.0
NAMES = {"DROP_SHADOW": "Drop shadow", "INNER_SHADOW": "Inner shadow",
         "LAYER_BLUR": "Layer blur", "BACKGROUND_BLUR": "Background blur"}
_COLS = ("type", "color", "alpha", "x", "y", "radius", "spread")


def _n(v) -> str:
    return "0" if v is None else f"{v:g}"


def label(e: dict) -> str:
    name = NAMES.get(e["type"], e["type"].lower())
    if e["type"] in ("LAYER_BLUR", "BACKGROUND_BLUR"):
        return f"{name} {_n(e['radius'])}"
    return f"{name} {_n(e['x'])} {_n(e['y'])} · blur {_n(e['radius'])}" + (
        f" · spread {_n(e['spread'])}" if e["spread"] else "")


def _row(r) -> dict:
    return dict(zip(_COLS, r))


def catalog(con) -> list[dict]:
    """Эффекты из стилей: каждое сочетание параметров и стили, в которых оно встречается."""
    seen: dict[tuple, dict] = {}
    for src, *r, uses in con.execute(
            "SELECT src, type, color, alpha, x, y, radius, spread, COUNT(*) FROM effects"
            " WHERE src LIKE 's:%' GROUP BY src, type, color, alpha, x, y, radius, spread"):
        key = tuple(r)
        e = seen.setdefault(key, {**_row(r), "styles": [], "uses": 0})
        e["styles"].append(src[2:])
        e["uses"] += uses
    out = list(seen.values())
    for e in out:
        e["label"] = label(e)
        e["styles"].sort()
    out.sort(key=lambda e: (-e["uses"], e["label"]))
    return out


def _close(a: dict, b: dict) -> bool:
    if a["type"] != b["type"]:
        return False
    if a["color"] and b["color"]:
        if colorm.de2000(colorm.lab(a["color"]), colorm.lab(b["color"])) >= 3 or abs((a["alpha"] or 0) - (b["alpha"] or 0)) > 5:
            return False
    for k, lim in (("x", NEAR_OFFSET), ("y", NEAR_OFFSET), ("radius", NEAR_RADIUS), ("spread", NEAR_OFFSET)):
        if abs((a[k] or 0) - (b[k] or 0)) > lim:
            return False
    return True


def classify(e: dict, styles: list[dict]) -> dict:
    key = tuple(e[c] for c in _COLS)
    for s in styles:
        if tuple(s[c] for c in _COLS) == key:
            return {"status": "unbound", "styles": s["styles"]}
    for s in styles:
        if _close(e, s):
            return {"status": "near", "styles": s["styles"], "nearest": s["label"]}
    return {"status": "off", "styles": []}


def report(con, filt: Filter) -> dict:
    where, args = filt.where()
    styles = catalog(con)
    items, totals = [], {"styled": 0, "unbound": 0, "near": 0, "off": 0}
    for row in con.execute(
            "SELECT e.src IS NOT NULL, e.type, e.color, e.alpha, e.x, e.y, e.radius, e.spread, COUNT(*),"
            " COUNT(DISTINCT n.file_key || '|' || IFNULL(n.screen, '')), COUNT(DISTINCT n.file_key), MIN(n.first_seen)"
            " FROM effects e JOIN nodes n ON n.file_key = e.file_key AND n.id = e.node_id" + NODE_JOIN +
            f" WHERE {where} AND {MANUAL}"
            " GROUP BY e.src IS NOT NULL, e.type, e.color, e.alpha, e.x, e.y, e.radius, e.spread"
            " ORDER BY 9 DESC", args):
        styled, *r, uses, screens, files, first = row
        if styled:
            totals["styled"] += uses
            continue
        e = _row(r)
        e.update(label=label(e), uses=uses, screens=screens, files=files, first_seen=first)
        e.update(classify(e, styles))
        totals[e["status"]] += uses
        items.append(e)
    return {"styles": styles, "items": items, "totals": totals}


def condition(q: dict) -> tuple[str, list]:
    """Слои с этим эффектом, набранным вручную."""
    def num(k):
        v = q.get(k)
        return None if v in (None, "", "null") else round(float(v), 2)
    try:
        vals = [q.get("type") or "", q.get("color") or None,
                None if q.get("alpha") in (None, "", "null") else int(q.get("alpha")),
                num("x"), num("y"), num("radius"), num("spread")]
    except ValueError:
        raise ValueError("Effect parameters must be numbers")
    cond = (f"{MANUAL} AND (n.file_key, n.id) IN (SELECT e.file_key, e.node_id FROM effects e WHERE e.src IS NULL AND "
            + " AND ".join(f"e.{c} IS ?" for c in _COLS) + ")")
    return cond, vals


# ---------------------------------------------------------------- картинки

def images(con, filt: Filter, limit: int = 300) -> dict:
    """Картинки: одна и та же картинка в разных местах — одна строка. Один проход."""
    where, args = filt.where()
    rows = con.execute(
        "SELECT i.ref, COUNT(*), COUNT(DISTINCT n.file_key || '|' || IFNULL(n.screen, '')),"
        " COUNT(DISTINCT n.file_key), GROUP_CONCAT(DISTINCT i.mode), MIN(n.first_seen), MIN(n.file_key),"
        " MAX(n.w), MAX(n.h), MIN(n.name)"
        " FROM images i JOIN nodes n ON n.file_key = i.file_key AND n.id = i.node_id" + NODE_JOIN +
        f" WHERE {where} GROUP BY i.ref", args).fetchall()
    rows.sort(key=lambda r: (-r[1], r[0]))
    items = [{"ref": ref, "uses": uses, "screens": screens, "files": files,
              "modes": sorted((modes or "").split(",")), "first_seen": first, "file_key": fk,
              "max_w": (w or 0) / 10, "max_h": (h or 0) / 10, "name": name}
             for ref, uses, screens, files, modes, first, fk, w, h, name in rows[:limit]]
    return {"total": len(rows), "total_uses": sum(r[1] for r in rows),
            "once": sum(1 for r in rows if r[1] == 1), "heavy": sum(1 for r in rows if r[1] >= 20), "items": items}


def image_condition(q: dict) -> tuple[str, list]:
    ref = q.get("ref")
    if not ref:
        raise ValueError("Choose an image")
    return "(n.file_key, n.id) IN (SELECT i.file_key, i.node_id FROM images i WHERE i.ref = ?)", [ref]
