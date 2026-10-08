"""Комментарии файлов: открытые и закрытые обсуждения по экранам.

Figma отдаёт комментарии отдельным лёгким запросом, поэтому они забираются при каждом
обновлении, даже если сам файл не менялся: комментарии появляются и закрываются без новой
версии файла.

У каждого обсуждения — экран, к которому оно приколото, ответы, давность, а у закрытого —
сколько дней оно было открыто. Видно, где обсуждают больше всего, что висит давно и как
быстро вопросы закрываются.

Токену нужны права на чтение комментариев. Если их нет, остальное работает как обычно,
а раздел подсказывает, какой токен нужен.
"""

from __future__ import annotations

import calendar
import time

from .figma import Figma, FigmaError
from .filters import Filter
from .inventory import figma_link

STALE_DAYS = 30               # открытое обсуждение старше — давно висящее


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _who(u) -> str:
    return (u or {}).get("handle") or "Someone"


def fetch(con, figma: Figma, key: str) -> None:
    """Забирает все комментарии файла. Ошибка здесь не мешает загрузке макетов."""
    from . import db as dbm
    try:
        got = figma.get_json(f"/files/{key}/comments")
    except FigmaError as e:
        with dbm.writing(con):
            con.execute("INSERT OR REPLACE INTO activity VALUES (?, 'comments', ?, ?)", (key, _now(), e.code))
        return
    rows = []
    for c in got.get("comments") or []:
        meta = c.get("client_meta") or {}
        node = meta.get("node_id") if isinstance(meta, dict) else None
        rows.append((key, str(c.get("id")), str(c.get("parent_id") or "") or None, node, c.get("message") or "",
                     _who(c.get("user")), c.get("created_at"), c.get("resolved_at")))
    with dbm.writing(con):
        con.execute("DELETE FROM comments WHERE file_key = ?", (key,))
        con.executemany("INSERT OR REPLACE INTO comments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.execute("INSERT OR REPLACE INTO activity VALUES (?, 'comments', ?, NULL)", (key, _now()))


def _files(con, filt: Filter) -> list[str]:
    # Файлы проекта, а без проекта — все загруженные.
    sql, args = "SELECT file_key FROM files", []
    if filt.project is not None:
        sql, args = "SELECT DISTINCT file_key FROM sources WHERE project_id = ?", [filt.project]
    keys = [r[0] for r in con.execute(sql, args) if r[0]]
    return [k for k in keys if not filt.files or k in filt.files]


def _ts(iso: str | None) -> float | None:
    try:
        return calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def _days(a: float | None, b: float | None) -> int | None:
    return int((b - a) // 86400) if a is not None and b is not None else None


def report(con, filt: Filter) -> dict:
    keys = _files(con, filt)
    if not keys:
        return {"threads": [], "access": [], "checked": False, "screens": [], "authors": [], "totals": {}}
    marks = ",".join("?" * len(keys))
    names = dict(con.execute(f"SELECT file_key, name FROM files WHERE file_key IN ({marks})", keys))
    now = time.time()

    replies: dict[tuple, list] = {}
    for fk, parent, who, msg, at in con.execute(
            f"SELECT file_key, parent_id, author, message, created_at FROM comments WHERE file_key IN ({marks})"
            " AND parent_id IS NOT NULL ORDER BY created_at", keys):
        replies.setdefault((fk, parent), []).append({"author": who, "message": msg, "created_at": at})

    # Обсуждение — первый комментарий и ответы на него; экран — по слою, к которому он приколот.
    threads = []
    for fk, cid, node, msg, who, created, resolved, screen, sname, pname in con.execute(
            "SELECT c.file_key, c.id, c.node_id, c.message, c.author, c.created_at, c.resolved_at,"
            " n.screen, (SELECT name FROM nodes s WHERE s.file_key = n.file_key AND s.id = n.screen), pg.name"
            " FROM comments c LEFT JOIN nodes n ON n.file_key = c.file_key AND n.id = c.node_id"
            " LEFT JOIN pages pg ON pg.file_key = n.file_key AND pg.page_id = n.page_id"
            f" WHERE c.file_key IN ({marks}) AND c.parent_id IS NULL ORDER BY c.created_at DESC", keys):
        t0, t1 = _ts(created), _ts(resolved)
        rs = replies.get((fk, cid), [])
        last = rs[-1]["created_at"] if rs else created
        threads.append({
            "file_key": fk, "file": names.get(fk) or fk, "id": cid, "message": msg, "author": who,
            "created_at": created, "resolved_at": resolved, "last_at": last, "open": not resolved,
            "age": _days(t0, now), "open_days": _days(t0, t1) if resolved else None,
            "quiet": _days(_ts(last), now),                   # сколько дней без ответа
            "replies": rs, "people": sorted({who, *(r["author"] for r in rs)}),
            "page": pname, "screen": sname, "screen_id": screen, "node_id": node,
            "screen_link": figma_link(fk, screen) if screen else None,
            "link": figma_link(fk, node) + f"#{cid}"})
    for t in threads:
        t["stale"] = t["open"] and t["age"] is not None and t["age"] > STALE_DAYS

    errors = [names.get(fk) or fk for fk, err in con.execute(
        f"SELECT file_key, error FROM activity WHERE kind = 'comments' AND file_key IN ({marks})", keys) if err]
    checked = bool(con.execute(f"SELECT 1 FROM activity WHERE kind = 'comments' AND file_key IN ({marks}) LIMIT 1",
                               keys).fetchone())

    open_ = [t for t in threads if t["open"]]
    done = [t for t in threads if not t["open"] and t["open_days"] is not None]
    by_screen: dict[tuple, dict] = {}
    for t in threads:
        if not t["screen_id"]:
            continue
        s = by_screen.setdefault((t["file_key"], t["screen_id"]), {"file": t["file"], "page": t["page"] or "",
                                                                    "screen": t["screen"] or "", "open": 0, "resolved": 0,
                                                                    "link": figma_link(t["file_key"], t["screen_id"])})
        s["open" if t["open"] else "resolved"] += 1
    screens = sorted(by_screen.values(), key=lambda s: (-s["open"], -s["resolved"], s["screen"]))
    authors: dict[str, list] = {}
    for t in threads:
        a = authors.setdefault(t["author"], [0, 0])
        a[0 if t["open"] else 1] += 1
    days = sorted(t["open_days"] for t in done)
    return {"threads": threads, "access": errors, "checked": checked, "screens": screens,
            "authors": [{"name": k, "open": v[0], "resolved": v[1]} for k, v in sorted(authors.items(), key=lambda kv: -sum(kv[1]))],
            "files": sorted({t["file"] for t in threads}),
            "totals": {"threads": len(threads), "open": len(open_), "resolved": len(threads) - len(open_),
                       "stale": sum(1 for t in open_ if t["stale"]),
                       "unanswered": sum(1 for t in open_ if not t["replies"]),
                       "median_days": days[len(days) // 2] if days else None,
                       "week_new": sum(1 for t in threads if (t["age"] if t["age"] is not None else 999) <= 7),
                       "week_resolved": sum(1 for t in done if _days(_ts(t["resolved_at"]), now) is not None
                                            and _days(_ts(t["resolved_at"]), now) <= 7)}}
