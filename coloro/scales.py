"""Отступы, скругления и толщина обводки против шкалы дизайн-системы.

Шкала выводится из самих макетов, как и система стилей в типографике: значения, привязанные
к переменным, — это и есть шкала. Если в файлах переменных для этих чисел нет вовсе, берётся
привычная сетка: отступы кратны 4 (и 2 для совсем мелких), скругления кратны 2, обводка —
0,5…4 px. Откуда взята шкала, экран всегда говорит.

Каждое число, набранное вручную, получает статус:

  unbound — значение есть в шкале, но не привязано к переменной → привязать
  near    — до значения шкалы не больше пикселя → поправить на значение шкалы
  off     — такого значения в шкале нет → решить, нужно ли оно

Скругление не меньше половины меньшей стороны — это «таблетка»: какое там число, не видно
глазом, и оно не ошибка. Считаются только слои, положенные на экран вручную: внутри
компонента и у самого инстанса эти числа задаёт библиотека.
"""

from __future__ import annotations

from .filters import NODE_JOIN, Filter

GROUPS = {
    "spacing": ("gap", "padding"),
    "radius": ("radius",),
    "stroke": ("stroke",),
}
NEAR = {"spacing": 1.0, "radius": 1.0, "stroke": 0.5}
STROKE_GRID = (0.5, 1, 1.5, 2, 3, 4)

# Слой, положенный на экран вручную, и не сам инстанс: у инстанса отступы — от компонента.
MANUAL = "n.pinst IS NULL AND n.type != 'INSTANCE'"
# Скругление-«таблетка»: размеры в базе в десятых долях пикселя.
_PILL = "(p.kind = 'radius' AND n.w IS NOT NULL AND n.h IS NOT NULL AND p.value * 20 >= MIN(n.w, n.h))"


def _on_grid(group: str, v: float) -> bool:
    if group == "spacing":
        return v == 2 or (v % 4 == 0)
    if group == "radius":
        return v % 2 == 0
    return v in STROKE_GRID


def scale(con, group: str) -> dict:
    """Шкала группы: привязанные значения по всем файлам, иначе — привычная сетка."""
    kinds = GROUPS[group]
    rows = con.execute(
        f"SELECT value, COUNT(*) FROM props WHERE bound = 1 AND kind IN ({','.join('?' * len(kinds))})"
        " GROUP BY value ORDER BY value", kinds).fetchall()
    if rows:
        return {"source": "variables", "values": [{"value": v, "uses": n} for v, n in rows]}
    return {"source": "grid", "values": []}


def classify(group: str, v: float, sc: dict) -> dict:
    if sc["source"] == "variables":
        vals = [s["value"] for s in sc["values"]]
        if v in vals:
            return {"status": "unbound", "nearest": v}
        nearest = min(vals, key=lambda x: (abs(x - v), x))
    else:
        if _on_grid(group, v):
            return {"status": "ok", "nearest": v}
        if group == "stroke":
            nearest = min(STROKE_GRID, key=lambda x: (abs(x - v), x))
        else:
            step = 4 if group == "spacing" and v > 3 else 2
            nearest = max(step, round(v / step) * step)
    status = "near" if abs(nearest - v) <= NEAR[group] else "off"
    return {"status": status, "nearest": nearest}


def report(con, filt: Filter) -> dict:
    """По каждой группе: шкала, значения, набранные вручную, со статусом и счётом."""
    where, args = filt.where()
    rows = con.execute(
        "SELECT p.kind, p.value, p.bound, " + _PILL + " AS pill, COUNT(*),"
        " COUNT(DISTINCT n.file_key || '|' || IFNULL(n.screen, '')), COUNT(DISTINCT n.file_key),"
        " MIN(n.first_seen)"
        " FROM props p JOIN nodes n ON n.file_key = p.file_key AND n.id = p.node_id" + NODE_JOIN +
        f" WHERE {where} AND {MANUAL}"
        " GROUP BY p.kind, p.value, p.bound, pill", args).fetchall()
    kind_group = {k: g for g, ks in GROUPS.items() for k in ks}
    out = {}
    for group in GROUPS:
        sc = scale(con, group)
        out[group] = {"source": sc["source"], "scale": sc["values"], "items": [],
                      "totals": {"bound": 0, "pill": 0, "ok": 0, "unbound": 0, "near": 0, "off": 0}}
    acc: dict[tuple, dict] = {}
    for kind, value, bound, pill, uses, screens, files, first in rows:
        g = kind_group.get(kind)
        if g is None:
            continue
        tot = out[g]["totals"]
        if bound:
            tot["bound"] += uses
            continue
        if pill:
            tot["pill"] += uses
            continue
        it = acc.setdefault((g, value), {"group": g, "value": value, "uses": 0, "screens": 0, "files": 0,
                                         "kinds": {}, "first_seen": first})
        it["uses"] += uses
        # Экраны и файлы по разным видам могут совпадать — берём наибольшее, это нижняя оценка.
        it["screens"] = max(it["screens"], screens)
        it["files"] = max(it["files"], files)
        it["kinds"][kind] = it["kinds"].get(kind, 0) + uses
        if first and (not it["first_seen"] or first < it["first_seen"]):
            it["first_seen"] = first
    for (g, value), it in acc.items():
        it.update(classify(g, value, {"source": out[g]["source"], "values": out[g]["scale"]}))
        out[g]["totals"][it["status"]] += it["uses"]
        out[g]["items"].append(it)
    for g in out:
        out[g]["items"].sort(key=lambda i: (-i["uses"], i["value"]))
    return out


def condition(q: dict) -> tuple[str, list]:
    """Слои, у которых в группе есть это значение, набранное вручную, — для поиска мест."""
    group = q.get("group") or "spacing"
    if group not in GROUPS:
        raise ValueError("Unknown group")
    try:
        value = round(float(q.get("value")), 2)
    except (TypeError, ValueError):
        raise ValueError("The value must be a number")
    kinds = GROUPS[group]
    cond = (f"{MANUAL} AND (n.file_key, n.id) IN (SELECT p.file_key, p.node_id FROM props p"
            f" WHERE p.kind IN ({','.join('?' * len(kinds))}) AND p.value = ? AND p.bound = 0)")
    args: list = [*kinds, value]
    if group == "radius":
        cond += " AND NOT (n.w IS NOT NULL AND n.h IS NOT NULL AND ? * 20 >= MIN(n.w, n.h))"
        args.append(value)
    return cond, args


def per_file(con, filt: Filter) -> dict[str, dict]:
    """Числа, набранные вручную, и сколько из них мимо шкалы (почти и мимо), по файлам."""
    where, args = filt.where()
    scales = {g: scale(con, g) for g in GROUPS}
    kind_group = {k: g for g, ks in GROUPS.items() for k in ks}
    out: dict[str, dict] = {}
    for fk, kind, value, bound, uses in con.execute(
            "SELECT n.file_key, p.kind, p.value, p.bound, COUNT(*)"
            " FROM props p JOIN nodes n ON n.file_key = p.file_key AND n.id = p.node_id" + NODE_JOIN +
            f" WHERE {where} AND {MANUAL} AND NOT {_PILL}"
            " GROUP BY n.file_key, p.kind, p.value, p.bound", args):
        g = kind_group.get(kind)
        if not g:
            continue
        m = out.setdefault(fk, {"props": 0, "scale_off": 0})
        m["props"] += uses
        if not bound and classify(g, value, scales[g])["status"] in ("near", "off"):
            m["scale_off"] += uses
    return out
