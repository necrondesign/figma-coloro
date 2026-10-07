"""Загрузка файла Figma в базу.

Порядок:
 1. Лёгкий запрос (depth=1) — имя, версия, страницы. Если версия та же и формат данных тот же —
    файл не трогаем: качать нечего.
 2. Запрос со списком верхних слоёв страниц (depth=2).
 3. Страница качается пачками верхних слоёв, а не целиком: так в памяти лежит пачка, а не вся
    страница (на больших файлах одна страница — это сотни мегабайт JSON). Оборвался ответ —
    пачка делится пополам, одиночный слой — раскрывается до детей.
 4. Страница записывается в базу одной транзакцией сразу, как скачалась. Не скачалась —
    в базе остаются её прежние данные, а у страницы появляется причина и метка «не загружена»;
    следующее обновление попробует её снова. Остальные страницы это не задевает.
 5. «Остановить» срабатывает между пачками: недокачанная страница не записывается вовсе,
    поэтому в базе никогда не бывает половины страницы.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import db as dbm
from . import rules
from .figma import Figma, FigmaError, Truncated
from .walk import Ctx, Out, child_ctx, walk

BATCH = 8          # верхних слоёв страницы в одном запросе
MAX_DEPTH = 40     # насколько глубоко можно раскрывать один слой, если он не скачивается целиком

NODE_COLS = 20
PAINT_COLS = 9


class Stopped(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch_into(figma: Figma, key: str, ids: list[str], ctx: Ctx, styles: dict, intern,
                first_seen: dict, now: str, out: Out, stop, depth: int = 0) -> None:
    if stop and stop.is_set():
        raise Stopped()
    try:
        resp = figma.nodes(key, ids)
    except Truncated:
        if len(ids) > 1:
            mid = len(ids) // 2
            _fetch_into(figma, key, ids[:mid], ctx, styles, intern, first_seen, now, out, stop, depth)
            _fetch_into(figma, key, ids[mid:], ctx, styles, intern, first_seen, now, out, stop, depth)
            return
        if depth >= MAX_DEPTH:
            raise
        # Один слой не помещается в ответ — берём его без внуков и раскрываем по детям.
        head = figma.nodes(key, ids, depth=1)
        entry = (head.get("nodes") or {}).get(ids[0])
        if not entry or not entry.get("document"):
            return
        styles.update(entry.get("styles") or {})
        node = entry["document"]
        walk(node, ctx, styles, intern, first_seen, now, out, children=False)
        kids = [k.get("id") for k in node.get("children") or [] if k.get("id")]
        for i in range(0, len(kids), BATCH):
            _fetch_into(figma, key, kids[i:i + BATCH], child_ctx(node, ctx), styles, intern,
                        first_seen, now, out, stop, depth + 1)
        return
    for nid in ids:
        entry = (resp.get("nodes") or {}).get(nid)
        if not entry or not entry.get("document"):
            continue                       # слой удалили между запросами
        styles.update(entry.get("styles") or {})
        walk(entry["document"], ctx, styles, intern, first_seen, now, out)


def _write_page(con, key: str, page: dict, position: int, version: str, out: Out, now: str) -> None:
    pid = page["id"]
    with con:
        con.execute("DELETE FROM nodes WHERE file_key = ? AND page_id = ?", (key, pid))
        con.execute("DELETE FROM paints WHERE file_key = ? AND page_id = ?", (key, pid))
        con.executemany(f"INSERT OR REPLACE INTO nodes VALUES ({','.join('?' * NODE_COLS)})", out.nodes)
        con.executemany(f"INSERT INTO paints VALUES ({','.join('?' * PAINT_COLS)})", out.paints)
        con.execute(
            "INSERT OR REPLACE INTO pages (file_key, page_id, name, archived, position, version, loaded_at,"
            " status, error, nodes) VALUES (?, ?, ?, ?, ?, ?, ?, 'ok', NULL, ?)",
            (key, pid, page.get("name") or "", 1 if rules.is_archive(page.get("name")) else 0,
             position, version, now, len(out.nodes)))


def _mark_failed(con, key: str, page: dict, position: int, error: str) -> None:
    # Прежняя версия страницы и её данные остаются: следующее обновление попробует снова.
    with con:
        con.execute(
            "INSERT INTO pages (file_key, page_id, name, archived, position, status, error)"
            " VALUES (?, ?, ?, ?, ?, 'failed', ?)"
            " ON CONFLICT (file_key, page_id) DO UPDATE SET status = 'failed', error = excluded.error,"
            " name = excluded.name, position = excluded.position",
            (key, page["id"], page.get("name") or "", 1 if rules.is_archive(page.get("name")) else 0,
             position, error))


def load_file(con, figma: Figma, key: str, page_patterns=None, force: bool = False,
              stop: threading.Event | None = None, progress=None) -> dict:
    """Загружает один файл. Возвращает отчёт: что загружено, что пропущено и почему."""
    report = {"file_key": key, "name": None, "status": "ok", "pages_loaded": [], "pages_failed": [],
              "pages_skipped": [], "nodes": 0, "seconds": 0.0}
    t0 = time.monotonic()
    now = _now()
    say = progress or (lambda **_: None)

    head = figma.file_head(key, depth=1)
    version = str(head.get("version") or "")
    report["name"] = head.get("name") or key
    pages = [p for p in (head.get("document") or {}).get("children") or [] if p.get("type") == "CANVAS"]
    with con:
        con.execute(
            "INSERT INTO files (file_key, name, version, last_modified, checked_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (file_key) DO UPDATE SET name = excluded.name, version = excluded.version,"
            " last_modified = excluded.last_modified, checked_at = excluded.checked_at",
            (key, report["name"], version, head.get("lastModified"), now))
        # Страницы, которых в файле больше нет, уходят из базы вместе с их слоями.
        alive = {p["id"] for p in pages}
        for (pid,) in con.execute("SELECT page_id FROM pages WHERE file_key = ?", (key,)).fetchall():
            if pid not in alive:
                for table in ("nodes", "paints", "pages"):
                    con.execute(f"DELETE FROM {table} WHERE file_key = ? AND page_id = ?", (key, pid))

    fmt = (con.execute("SELECT format FROM files WHERE file_key = ?", (key,)).fetchone() or [None])[0]
    stored = {pid: (st, ver) for pid, st, ver in
              con.execute("SELECT page_id, status, version FROM pages WHERE file_key = ?", (key,))}
    todo = []
    for pos, p in enumerate(pages):
        if not rules.name_matches(p.get("name"), page_patterns):
            report["pages_skipped"].append(p.get("name"))
            continue
        st, ver = stored.get(p["id"], (None, None))
        if not force and fmt == dbm.FORMAT and st == "ok" and ver == version:
            continue                       # страница не менялась
        todo.append((pos, p))

    if todo:
        # Верхние слои каждой страницы — одним запросом на весь файл.
        tops = {p.get("id"): [c.get("id") for c in p.get("children") or [] if c.get("id")]
                for p in (figma.file_head(key, depth=2).get("document") or {}).get("children") or []}
        intern = dbm.Interner(con)
        for i, (pos, page) in enumerate(todo, 1):
            pid = page["id"]
            say(file=report["name"], page=page.get("name"), index=i, total=len(todo))
            first_seen = dict(con.execute(
                "SELECT id, first_seen FROM nodes WHERE file_key = ? AND page_id = ?", (key, pid)).fetchall())
            out, styles = Out(), {}
            ctx = Ctx(file_key=key, page_id=pid, parent_id=pid)
            try:
                ids = tops.get(pid) or []
                for j in range(0, len(ids), BATCH):
                    _fetch_into(figma, key, ids[j:j + BATCH], ctx, styles, intern, first_seen, now, out, stop)
            except Stopped:
                report["status"] = "stopped"
                break
            except FigmaError as e:
                _mark_failed(con, key, page, pos, str(e))
                report["pages_failed"].append({"page": page.get("name"), "error": str(e)})
                continue
            _write_page(con, key, page, pos, version, out, now)
            report["pages_loaded"].append(page.get("name"))
            report["nodes"] += len(out.nodes)

    if report["status"] == "ok" and report["pages_failed"]:
        report["status"] = "partial"
    if report["status"] == "ok":
        with con:
            con.execute("UPDATE files SET loaded_at = ?, format = ? WHERE file_key = ?", (now, dbm.FORMAT, key))
    if report["pages_loaded"]:
        # Статистика для планировщика запросов: без неё SQLite выбирает порядок соединения
        # таблиц вслепую и на больших базах может ошибиться на порядки.
        con.execute("ANALYZE")
    if not todo and report["status"] == "ok":
        report["status"] = "unchanged"
    report["seconds"] = round(time.monotonic() - t0, 1)
    return report


def update_all(db_path: str | Path, token: str, sources: list[dict], workers: int = 4, force: bool = False,
               stop: threading.Event | None = None, progress=None) -> list[dict]:
    """Обновляет все источники параллельно. Один файл из нескольких ссылок качается один раз.

    sources: [{"file_key": ..., "pages": [образцы] или None}]. Если хоть одна ссылка на файл
    не ограничивает страницы — берутся все.
    """
    merged: dict[str, list | None] = {}
    for s in sources:
        key, pats = s["file_key"], s.get("pages")
        if key not in merged:
            merged[key] = list(pats) if pats else None
        elif merged[key] is not None:
            merged[key] = None if not pats else sorted(set(merged[key]) | set(pats))

    figma = Figma(token)

    def one(item):
        key, pats = item
        con = dbm.connect(db_path)
        try:
            return load_file(con, figma, key, pats, force=force, stop=stop, progress=progress)
        except FigmaError as e:
            return {"file_key": key, "status": "failed", "error": str(e)}
        finally:
            con.close()

    with ThreadPoolExecutor(max_workers=max(1, min(8, workers))) as pool:
        return list(pool.map(one, merged.items()))
