"""Версии и комментарии файлов.

Figma отдаёт их отдельными лёгкими запросами, поэтому они забираются при каждом обновлении,
даже если сам файл не менялся: комментарии появляются и закрываются без новой версии.

  комментарии — обсуждения по экранам: открытые, закрытые, давно висящие; у каждого — экран,
               на котором он оставлен, и ссылка прямо на него;
  версии      — история файла: именованные версии с описанием и автосохранения. Рядом со
               снимками чисел проекта видно, после какой версии стало лучше или хуже.

Токену для этого нужны права на чтение комментариев и версий. Если их нет, остальное
работает как обычно, а раздел подсказывает, какой токен нужен.
"""

from __future__ import annotations

import calendar
import time
from urllib.parse import parse_qs, urlparse

from .figma import Figma, FigmaError
from .filters import Filter
from .inventory import figma_link

VERSION_PAGES = 10            # первая загрузка: до стольких страниц истории (по 50 версий)
STALE_DAYS = 30               # открытый комментарий старше — давно висящий


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _who(u) -> str:
    return (u or {}).get("handle") or "Someone"


def _status(con, key: str, kind: str, error: str | None) -> None:
    con.execute("INSERT OR REPLACE INTO activity (file_key, kind, checked_at, error) VALUES (?, ?, ?, ?)",
                (key, kind, _now(), error))


def fetch(con, figma: Figma, key: str) -> None:
    """Забирает комментарии и новые версии файла. Ошибка здесь не мешает загрузке макетов."""
    from . import db as dbm
    try:
        got = figma.get_json(f"/files/{key}/comments")
        rows = []
        for c in got.get("comments") or []:
            meta = c.get("client_meta") or {}
            node = meta.get("node_id") if isinstance(meta, dict) else None
            rows.append((key, str(c.get("id")), str(c.get("parent_id") or "") or None, node, c.get("message") or "",
                         _who(c.get("user")), c.get("created_at"), c.get("resolved_at")))
        with dbm.writing(con):
            con.execute("DELETE FROM comments WHERE file_key = ?", (key,))
            con.executemany("INSERT OR REPLACE INTO comments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            _status(con, key, "comments", None)
    except FigmaError as e:
        with dbm.writing(con):
            _status(con, key, "comments", e.code)

    try:
        known = {r[0] for r in con.execute("SELECT id FROM versions WHERE file_key = ?", (key,))}
        rows, params = [], {"page_size": 50}
        for _ in range(VERSION_PAGES if not known else 2):
            got = figma.get_json(f"/files/{key}/versions", params)
            batch = got.get("versions") or []
            fresh = [v for v in batch if str(v.get("id")) not in known]
            rows += [(key, str(v.get("id")), v.get("created_at"), v.get("label") or None, v.get("description") or None,
                      _who(v.get("user"))) for v in fresh]
            nxt = ((got.get("pagination") or {}).get("next_page")) or ""
            # Дошли до уже известных версий или история кончилась.
            if len(fresh) < len(batch) or not batch or not nxt:
                break
            # Следующая страница — по параметрам, которые дала сама Figma.
            params = {k: v[0] for k, v in parse_qs(urlparse(nxt).query).items()}
        with dbm.writing(con):
            con.executemany("INSERT OR REPLACE INTO versions VALUES (?, ?, ?, ?, ?, ?)", rows)
            _status(con, key, "versions", None)
    except FigmaError as e:
        with dbm.writing(con):
            _status(con, key, "versions", e.code)


def _files(con, filt: Filter) -> list[str]:
    # Файлы проекта, а без проекта — все загруженные.
    sql, args = "SELECT file_key FROM files", []
    if filt.project is not None:
        sql, args = "SELECT DISTINCT file_key FROM sources WHERE project_id = ?", [filt.project]
    keys = [r[0] for r in con.execute(sql, args) if r[0]]
    return [k for k in keys if not filt.files or k in filt.files]


def _days(iso: str | None, now: float) -> int | None:
    try:
        return int((now - calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))) // 86400)
    except (TypeError, ValueError):
        return None


def report(con, filt: Filter) -> dict:
    keys = _files(con, filt)
    if not keys:
        return {"comments": [], "versions": [], "access": {}, "totals": {}}
    marks = ",".join("?" * len(keys))
    names = dict(con.execute(f"SELECT file_key, name FROM files WHERE file_key IN ({marks})", keys))
    now = time.time()

    # Обсуждение — первый комментарий и ответы на него; экран — по слою, к которому он приколот.
    replies: dict[tuple, list] = {}
    for fk, parent, who, msg, at in con.execute(
            f"SELECT file_key, parent_id, author, message, created_at FROM comments WHERE file_key IN ({marks})"
            " AND parent_id IS NOT NULL ORDER BY created_at", keys):
        replies.setdefault((fk, parent), []).append({"author": who, "message": msg, "created_at": at})
    threads = []
    for fk, cid, node, msg, who, created, resolved, screen, sname, pname in con.execute(
            "SELECT c.file_key, c.id, c.node_id, c.message, c.author, c.created_at, c.resolved_at,"
            " n.screen, (SELECT name FROM nodes s WHERE s.file_key = n.file_key AND s.id = n.screen), pg.name"
            " FROM comments c LEFT JOIN nodes n ON n.file_key = c.file_key AND n.id = c.node_id"
            " LEFT JOIN pages pg ON pg.file_key = n.file_key AND pg.page_id = n.page_id"
            f" WHERE c.file_key IN ({marks}) AND c.parent_id IS NULL ORDER BY c.created_at DESC", keys):
        age = _days(created, now)
        threads.append({"file_key": fk, "file": names.get(fk) or fk, "id": cid, "message": msg, "author": who,
                        "created_at": created, "resolved_at": resolved, "open": not resolved, "age": age,
                        "stale": not resolved and age is not None and age > STALE_DAYS,
                        "replies": replies.get((fk, cid), []), "page": pname, "screen": sname,
                        "screen_id": screen, "node_id": node,
                        "link": figma_link(fk, node) + f"#{cid}"})

    versions = [{"file_key": fk, "file": names.get(fk) or fk, "id": vid, "created_at": at, "label": label,
                 "description": desc, "author": who,
                 "link": f"https://www.figma.com/design/{fk}/?version-id={vid}"}
                for fk, vid, at, label, desc, who in con.execute(
                    f"SELECT file_key, id, created_at, label, description, author FROM versions WHERE file_key IN ({marks})"
                    " ORDER BY created_at DESC LIMIT 2000", keys)]

    access = {}
    for fk, kind, error in con.execute(f"SELECT file_key, kind, error FROM activity WHERE file_key IN ({marks})", keys):
        if error:
            access.setdefault(kind, []).append(names.get(fk) or fk)

    open_ = [t for t in threads if t["open"]]
    by_screen: dict[tuple, int] = {}
    for t in open_:
        if t["screen_id"]:
            k = (t["file"], t["page"] or "", t["screen"] or "")
            by_screen[k] = by_screen.get(k, 0) + 1
    week = [v for v in versions if (_days(v["created_at"], now) or 999) <= 7]
    return {"comments": threads, "versions": versions, "access": access,
            "checked": bool(con.execute(f"SELECT 1 FROM activity WHERE file_key IN ({marks}) LIMIT 1", keys).fetchone()),
            "busy_screens": [{"file": f, "page": p, "screen": s, "open": n}
                             for (f, p, s), n in sorted(by_screen.items(), key=lambda kv: -kv[1])[:8]],
            "totals": {"threads": len(threads), "open": len(open_), "resolved": len(threads) - len(open_),
                       "stale": sum(1 for t in open_ if t["stale"]), "versions": len(versions),
                       "named": sum(1 for v in versions if v["label"]), "week": len(week),
                       "authors": len({v["author"] for v in week})}}
