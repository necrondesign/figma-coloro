"""Цвета: что есть в макетах, что из этого мимо дизайн-системы и где оно лежит.

У каждого цвета — статус относительно справочника токенов:
  token — значение совпадает с токеном
  near  — на вид почти токен (разница глазом не заметна или едва заметна) → заменить на токен
  alpha — цвет как у токена, но с другой прозрачностью: белый 40% при токене белого 100%.
          Самая частая история — подложки и затемнения → токен нужной прозрачности
  off   — далеко от всех токенов → добавить в систему или заменить
  none  — справочник не загружен, сравнивать не с чем

И отдельно — сколько применений набрано вручную: цвет может совпадать с токеном по значению,
но не быть к нему привязан. Это самое частое и самое простое исправление.

Каждое место ведёт на слой в Figma.
"""

from __future__ import annotations

from urllib.parse import quote

from . import color as colorm
from .filters import JOIN, Filter
from .tokens import Index

RARE = 2   # столько применений и меньше — цвет «редкий», скорее всего опечатка

# Краска со слоем — для мест, где нужны название и тип слоя.
_WITH_NODE = " JOIN nodes n ON n.file_key = p.file_key AND n.id = p.node_id"


def classify(c: str, a: int, idx: Index) -> dict:
    if not idx:
        return {"status": "none", "tokens": [], "nearest": None}
    got = idx.classified.get((c, a))
    if got is None:
        got = idx.classified[(c, a)] = _classify(c, a, idx)
    return got


def _classify(c: str, a: int, idx: Index) -> dict:
    names = idx.exact(c, a)
    if names:
        return {"status": "token", "tokens": names, "nearest": None}
    # Порядок важен. Сначала «почти токен» — с учётом прозрачности: если есть токен того же
    # вида и той же прозрачности, это он. Только если такого нет, проверяем «тот же цвет,
    # другая прозрачность» — иначе почти совпавший цвет уходил бы не в свою категорию.
    near = idx.nearest(c, a)
    nearest = None
    if near:
        name, tc, ta, de, da = near
        nearest = {"name": name, "color": tc, "alpha": ta, "label": colorm.label(tc, ta), "de": de, "dalpha": da}
        if de <= colorm.NEAR_DE and da <= colorm.NEAR_ALPHA:
            return {"status": "near", "tokens": [], "nearest": nearest}
    same = idx.same_colour(c)
    if same and abs(same[2] - a) > colorm.NEAR_ALPHA:
        name, tc, ta, de = same
        return {"status": "alpha", "tokens": [], "nearest": {
            "name": name, "color": tc, "alpha": ta, "label": colorm.label(tc, ta),
            "de": round(de, 2), "dalpha": abs(ta - a)}}
    return {"status": "off", "tokens": [], "nearest": nearest}


def aggregate(con, filt: Filter) -> list[tuple]:
    """Применения цвета по файлам — один проход по краскам, без слоев.

    Повторные стопы одного градиента схлопнуты ещё при загрузке, так что каждая строка
    краски — одно применение цвета. Из этих строк собираются и общий список цветов, и
    числа по файлам на общей картине."""
    where, args = filt.where(paints=True)
    return con.execute(
        # COUNT(CASE …), а не SUM(условие): при пустом src сравнение даёт NULL, и сумма — тоже.
        "SELECT p.file_key, p.color, p.alpha, COUNT(*), COUNT(CASE WHEN p.kind = 'solid' THEN 1 END),"
        " COUNT(CASE WHEN p.kind = 'stop' THEN 1 END), COUNT(CASE WHEN p.src IS NULL THEN 1 END),"
        " COUNT(CASE WHEN p.src = 'v' THEN 1 END), COUNT(CASE WHEN p.src LIKE 's:%' THEN 1 END),"
        " COUNT(DISTINCT IFNULL(p.screen, '')), MIN(p.first_seen)"
        " FROM paints p" + JOIN + f" WHERE {where} GROUP BY p.file_key, p.color, p.alpha", args).fetchall()


def colours(con, filt: Filter, idx: Index, rows: list[tuple] | None = None) -> list[dict]:
    """Все цвета под фильтром, от самых частых к редким, со статусом относительно токенов."""
    acc: dict[tuple, list] = {}
    for fk, c, a, uses, flat, grad, raw, var, sty, screens, first in (rows if rows is not None else aggregate(con, filt)):
        m = acc.get((c, a))
        if m is None:
            acc[(c, a)] = [uses, flat, grad, raw, var, sty, 1, screens, first]
            continue
        for i, v in enumerate((uses, flat, grad, raw, var, sty, 1, screens)):
            m[i] += v
        if first and (not m[8] or first < m[8]):
            m[8] = first
    out = []
    for (c, a), (uses, flat, grad, raw, var, sty, files, screens, first) in sorted(
            acc.items(), key=lambda kv: (-kv[1][0], kv[0][0], kv[0][1])):
        item = {"color": c, "alpha": a, "label": colorm.label(c, a), "family": colorm.family(c),
                "uses": uses, "flat": flat, "grad": grad, "raw": raw, "var": var, "style": sty,
                "files": files, "screens": screens, "first_seen": first,
                "rare": uses <= RARE}
        item.update(classify(c, a, idx))
        # Значение токена, но где-то набрано вручную — привязать.
        item["unbound"] = item["status"] == "token" and raw > 0
        out.append(item)
    return out


def stray(items: list[dict]) -> dict:
    """Левые цвета по категориям — у каждой своё действие."""
    return {
        "near": [i for i in items if i["status"] == "near"],
        "alpha": [i for i in items if i["status"] == "alpha"],
        "off": [i for i in items if i["status"] == "off"],
        "unbound": [i for i in items if i["unbound"]],
        "rare": [i for i in items if i["rare"] and i["status"] != "token"],
    }


def figma_link(file_key: str, node_id: str | None) -> str:
    """Ссылка на слой. https-адрес открывается и в приложении Figma, и в браузере —
    схема figma:// без приложения не делает ничего и ничего не сообщает."""
    url = f"https://www.figma.com/design/{file_key}/"
    if node_id:
        url += "?node-id=" + quote(node_id.replace(":", "-"), safe="-")
    return url


def screens(con, filt: Filter, c: str, a: int, limit: int = 60, offset: int = 0) -> dict:
    """Где лежит цвет — по экранам: дизайнер думает экранами, а не слоями.

    Цвет из двух прямоугольников на сотне вариантов экрана — это сотня строк «экран — сколько
    мест — какие слои», а не двести строк с одинаковыми именами. Один запрос: итоги считаются
    из групп, названия экранов — только для показанной страницы."""
    where, args = filt.where(paints=True)
    rows = con.execute(
        "SELECT p.file_key, p.screen, COUNT(*), MIN(p.first_seen), MAX(f.name), MAX(pg.name), MIN(pg.position),"
        " GROUP_CONCAT(DISTINCT replace(n.name, ',', char(31))), COUNT(CASE WHEN p.src IS NULL THEN 1 END),"
        " SUM(p.hid), MAX(pg.archived)"
        " FROM paints p" + _WITH_NODE + JOIN +
        f" WHERE p.color = ? AND p.alpha = ? AND {where} GROUP BY p.file_key, p.screen",
        [c, a] + args).fetchall()
    rows.sort(key=lambda r: (r[4] or "", r[6] or 0, r[1] or ""))
    page = rows[offset:offset + limit]
    groups = []
    for fk, screen, count, first, fname, pname, _pos, names, raw, hid, archived in page:
        sname = None
        if screen:
            got = con.execute("SELECT name FROM nodes WHERE file_key = ? AND id = ?", (fk, screen)).fetchone()
            sname = got[0] if got else None
        layer_names = sorted({x.replace(chr(31), ",") for x in (names or "").split(",") if x})
        groups.append({
            "file_key": fk, "file": fname, "page": pname, "screen": sname or "без экрана", "screen_id": screen,
            "count": count, "raw": raw, "first_seen": first, "layers": layer_names[:4],
            "more_layers": max(0, len(layer_names) - 4), "hidden": bool(hid), "archived": bool(archived),
            "link": figma_link(fk, screen),
        })
    return {"total": len(rows), "total_places": sum(r[2] for r in rows), "items": groups,
            "limit": limit, "offset": offset}


def places(con, filt: Filter, c: str, a: int, limit: int = 200, offset: int = 0,
           file_key: str | None = None, screen: str | None = None) -> dict:
    """Где лежит цвет: файл, страница, экран, слой — и ссылка прямо на слой.
    С file_key и screen — только слои одного экрана."""
    where, args = filt.where(paints=True)
    base = (" FROM paints p" + _WITH_NODE + JOIN +
            " LEFT JOIN nodes s ON s.file_key = n.file_key AND s.id = n.screen"
            " LEFT JOIN vals sv ON sv.id = n.sect"
            " WHERE p.color = ? AND p.alpha = ? AND " + where)
    params = [c, a] + args
    if file_key:
        base += " AND n.file_key = ?"
        params.append(file_key)
        if screen:
            base += " AND n.screen = ?"
            params.append(screen)
        else:
            base += " AND n.screen IS NULL"
    total = con.execute("SELECT COUNT(*)" + base, params).fetchone()[0]
    rows = con.execute(
        "SELECT n.file_key, f.name, pg.name, s.name, n.screen, n.id, n.name, n.type, sv.v,"
        " p.slot, p.kind, p.src, n.anchor, n.first_seen, n.hid, pg.archived" + base +
        " ORDER BY f.name, pg.position, s.name, n.name LIMIT ? OFFSET ?",
        params + [limit, offset]).fetchall()
    items = []
    for (fk, fname, pname, sname, screen, nid, nname, ntype, sect, slot, kind, src, anchor, first,
         hid, archived) in rows:
        items.append({
            "file_key": fk, "file": fname, "page": pname, "screen": sname or "", "screen_id": screen,
            "node_id": nid, "name": nname, "type": ntype, "sections": sect or "",
            "slot": slot, "kind": kind, "source": src, "first_seen": first,
            "hidden": bool(hid), "archived": bool(archived),
            # Если слой внутри инстанса, ссылка ведёт на сам инстанс — на внутренний слой
            # Figma перейти не умеет.
            "link": figma_link(fk, anchor or screen),
            "exact_link": anchor == nid,
        })
    return {"total": total, "items": items, "limit": limit, "offset": offset}
