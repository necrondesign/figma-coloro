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

# Уникальные применения: сплошная краска — каждая; стоп градиента — один раз на цвет внутри
# одного градиента (два одинаковых стопа — одно применение цвета).
_USES = ("SELECT DISTINCT CASE WHEN p.kind = 'solid' THEN p.rowid END AS rid,"
         " p.file_key, p.node_id, p.slot, p.kind, p.color, p.alpha, p.src, p.grad,"
         " n.screen, n.first_seen FROM paints p" + JOIN + " WHERE ")


def classify(c: str, a: int, idx: Index) -> dict:
    if not idx:
        return {"status": "none", "tokens": [], "nearest": None}
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


def colours(con, filt: Filter, idx: Index) -> list[dict]:
    """Все цвета под фильтром, от самых частых к редким, со статусом относительно токенов."""
    where, args = filt.where()
    rows = con.execute(
        "WITH u AS (" + _USES + where + ")"
        " SELECT color, alpha, COUNT(*), SUM(kind = 'solid'), SUM(kind = 'stop'),"
        " SUM(src IS NULL), SUM(src = 'v'), SUM(src LIKE 's:%'),"
        " COUNT(DISTINCT file_key), COUNT(DISTINCT file_key || '|' || IFNULL(screen, '')), MIN(first_seen)"
        " FROM u GROUP BY color, alpha ORDER BY 3 DESC, 1", args).fetchall()
    out = []
    for c, a, uses, flat, grad, raw, var, sty, files, screens, first in rows:
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
    мест — какие слои», а не двести строк с одинаковыми именами."""
    where, args = filt.where()
    base = (" FROM paints p" + JOIN +
            " LEFT JOIN nodes s ON s.file_key = n.file_key AND s.id = n.screen"
            " WHERE p.color = ? AND p.alpha = ? AND " + where)
    params = [c, a] + args
    total_places = con.execute("SELECT COUNT(*)" + base, params).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM (SELECT 1" + base + " GROUP BY n.file_key, n.screen)", params).fetchone()[0]
    rows = con.execute(
        "SELECT n.file_key, f.name, pg.name, s.name, n.screen, COUNT(*), MIN(n.first_seen),"
        " GROUP_CONCAT(DISTINCT replace(n.name, ',', char(31))), SUM(p.src IS NULL), SUM(n.hid), MAX(pg.archived)" + base +
        " GROUP BY n.file_key, n.screen ORDER BY f.name, MIN(pg.position), s.name LIMIT ? OFFSET ?",
        params + [limit, offset]).fetchall()
    groups = []
    for fk, fname, pname, sname, screen, count, first, names, raw, hid, archived in rows:
        layer_names = sorted({x.replace(chr(31), ",") for x in (names or "").split(",") if x})
        groups.append({
            "file_key": fk, "file": fname, "page": pname, "screen": sname or "без экрана", "screen_id": screen,
            "count": count, "raw": raw, "first_seen": first, "layers": layer_names[:4],
            "more_layers": max(0, len(layer_names) - 4), "hidden": bool(hid), "archived": bool(archived),
            "link": figma_link(fk, screen),
        })
    return {"total": total, "total_places": total_places, "items": groups, "limit": limit, "offset": offset}


def places(con, filt: Filter, c: str, a: int, limit: int = 200, offset: int = 0,
           file_key: str | None = None, screen: str | None = None) -> dict:
    """Где лежит цвет: файл, страница, экран, слой — и ссылка прямо на слой.
    С file_key и screen — только слои одного экрана."""
    where, args = filt.where()
    base = (" FROM paints p" + JOIN +
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
