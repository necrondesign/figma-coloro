"""Локальный сервер: страницы инструмента и JSON-интерфейс к базе.

Безопасность — локальная база макетов не должна быть доступна никому, кроме человека за этим
компьютером:
- слушает только 127.0.0.1;
- никакого CORS: страницы отдаёт сам сервер, им он не нужен, а чужим сайтам — не положено;
- заголовок Host проверяется: без этого чужой сайт обходит запрет через подмену адреса
  (DNS rebinding);
- запросы, которые что-то меняют, принимаются только со своей страницы (Origin);
- токен Figma никогда не отдаётся обратно — только «задан или нет».
"""

from __future__ import annotations

import json
import os
import mimetypes
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db as dbm
from . import effects, health, inventory, memo, report, rules, scales, search, tokens, typography
from .figma import Figma, FigmaError
from .filters import Filter
from .load import update_all
from .textnorm import norm

HOME = Path.home() / ".coloro"
DB_PATH = HOME / "coloro.sqlite"
TOKEN_PATH = Path.home() / ".config" / "coloro" / "token"
LEGACY_TOKEN = Path.home() / ".config" / "figma-colors" / "token"
STATIC = Path(__file__).parent / "static"
PORT = 8800


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Адреса картинок Figma отдаёт на файл целиком и на время — кэш, чтобы не просить заново
# при каждом открытии экрана.
_IMAGE_URLS: dict[str, tuple[float, dict]] = {}
_IMAGE_LOCK = threading.Lock()
_IMAGE_TTL = 3600
# Экран картинок просит адреса сразу по всем файлам — к Figma пускаем не больше трёх разом.
_IMAGE_GATE = threading.Semaphore(3)


def image_urls(file_key: str) -> dict:
    with _IMAGE_LOCK:
        got = _IMAGE_URLS.get(file_key)
        if got and time.time() - got[0] < _IMAGE_TTL:
            return got[1]
    token = read_token()
    if not token:
        raise ValueError("A Figma access token is required. Add it in Settings.")
    with _IMAGE_GATE:
        with _IMAGE_LOCK:
            got = _IMAGE_URLS.get(file_key)       # пока ждали очереди, мог принести другой запрос
            if got and time.time() - got[0] < _IMAGE_TTL:
                return got[1]
        urls = (Figma(token).get_json(f"/files/{file_key}/images").get("meta") or {}).get("images") or {}
    with _IMAGE_LOCK:
        _IMAGE_URLS[file_key] = (time.time(), urls)
    return urls


# Превью компонентов: Figma рисует слой картинкой и отдаёт ссылку, живущую несколько недель.
# Запоминаем на сутки, рисуем пачками и не больше трёх запросов разом.
_PREVIEWS: dict[tuple[str, str], tuple[float, str | None]] = {}
_PREVIEW_TTL = 86400
_PREVIEW_BATCH = 40


def previews(file_key: str, ids: list[str]) -> dict:
    now = time.time()
    with _IMAGE_LOCK:
        have = {i: _PREVIEWS[(file_key, i)][1] for i in ids
                if (file_key, i) in _PREVIEWS and now - _PREVIEWS[(file_key, i)][0] < _PREVIEW_TTL}
    need = [i for i in ids if i not in have]
    if need:
        token = read_token()
        if not token:
            raise ValueError("A Figma access token is required. Add it in Settings.")
        figma = Figma(token)
        for k in range(0, len(need), _PREVIEW_BATCH):
            batch = need[k:k + _PREVIEW_BATCH]
            with _IMAGE_GATE:
                try:
                    got = figma.get_json(f"/images/{file_key}", {"ids": ",".join(batch), "format": "png", "scale": 1}).get("images") or {}
                except FigmaError:
                    got = {}       # слой не рисуется (удалён, слишком велик) — без превью, но не ошибка экрана
            with _IMAGE_LOCK:
                for i in batch:
                    _PREVIEWS[(file_key, i)] = (now, got.get(i))
                    have[i] = got.get(i)
    return have


def read_token() -> str:
    # Переменная окружения — как у команды load: удобно, когда токен лежит в другом месте.
    env = os.environ.get("FIGMA_TOKEN", "").strip()
    if env:
        return env
    for p in (TOKEN_PATH, LEGACY_TOKEN):
        if p.exists():
            t = p.read_text(encoding="utf-8").strip()
            if t:
                return t
    return ""


def save_token(value: str) -> None:
    clean = "".join(ch for ch in value if 33 <= ord(ch) <= 126)
    if len(clean) < 20:
        raise ValueError("The token is too short. Copy the whole token.")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_PATH.with_name(TOKEN_PATH.name + ".tmp")
    tmp.write_text(clean, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(TOKEN_PATH)


# ---------------------------------------------------------------- обновление

DEFAULT_WORKERS = 4


def workers(con) -> int:
    """Сколько файлов качать одновременно. По умолчанию 4 — на 32 файлах Figma ни разу не
    попросила подождать; больше — быстрее, но ближе к её лимиту."""
    got = con.execute("SELECT v FROM meta WHERE k = 'workers'").fetchone()
    try:
        return max(1, min(8, int(got[0]))) if got else DEFAULT_WORKERS
    except (TypeError, ValueError):
        return DEFAULT_WORKERS


class Job:
    """Одно обновление в фоне. Прогресс читает страница, остановить можно в любой момент."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.state = {"running": False}

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state))

    def start(self, sources: list[dict], force: bool, projects: list[int], n_workers: int) -> bool:
        with self.lock:
            if self.state.get("running"):
                return False
            self.stop.clear()
            self.state = {"running": True, "started": _now(), "files_total": len({s["file_key"] for s in sources}),
                          "files_done": 0, "current": {}, "reports": []}
        threading.Thread(target=self._run, args=(sources, force, projects, n_workers), daemon=True).start()
        return True

    def _progress(self, **kw):
        with self.lock:
            self.state.setdefault("current", {})[kw.get("file") or ""] = {
                "page": kw.get("page"), "index": kw.get("index"), "total": kw.get("total")}

    def _run(self, sources, force, projects, n_workers):
        reports = []
        try:
            reports = update_all(DB_PATH, read_token(), sources, workers=n_workers, force=force,
                                 stop=self.stop, progress=self._progress)
        except Exception as e:     # noqa: BLE001 — любая ошибка должна дойти до экрана, а не умереть в потоке
            reports = [{"status": "failed", "error": str(e)}]
        # Снимок для истории — по каждому проекту, файлы которого обновлялись.
        if any(r.get("pages_loaded") for r in reports):
            con = dbm.connect(DB_PATH)
            try:
                for pid in projects:
                    health.snapshot(con, tokens.load(con, pid), pid)
            finally:
                con.close()
        with self.lock:
            self.state.update(running=False, finished=_now(), reports=reports, current={},
                              files_done=len(reports), stopped=self.stop.is_set())


JOB = Job()


# ---------------------------------------------------------------- проекты и источники

def ensure_project(con) -> None:
    """Хотя бы один проект есть всегда: с него начинает человек, открывший coloro впервые."""
    if not con.execute("SELECT 1 FROM projects").fetchone():
        with dbm.writing(con):
            con.execute("INSERT INTO projects (name, created_at) VALUES ('My project', ?)", (_now(),))


def state(con) -> dict:
    ensure_project(con)
    files = {}
    for fk, name, ver, lm, checked, loaded, fmt in con.execute(
            "SELECT file_key, name, version, last_modified, checked_at, loaded_at, format FROM files"):
        files[fk] = {"name": name, "version": ver, "last_modified": lm, "checked_at": checked,
                     "loaded_at": loaded, "outdated_format": fmt != dbm.FORMAT, "pages": [], "nodes": 0}
    for fk, pid, name, archived, status, error, nodes, loaded in con.execute(
            "SELECT file_key, page_id, name, archived, status, error, nodes, loaded_at FROM pages"
            " ORDER BY file_key, position"):
        if fk in files:
            files[fk]["pages"].append({"id": pid, "name": name, "archived": bool(archived), "status": status,
                                       "error": error, "nodes": nodes, "loaded_at": loaded})
            files[fk]["nodes"] += nodes or 0
    srcs = []
    for sid, url, fk, node, pages, added, pid in con.execute(
            "SELECT id, url, file_key, node_id, pages, added_at, project_id FROM sources ORDER BY id"):
        srcs.append({"id": sid, "url": url, "file_key": fk, "node_id": node, "added_at": added, "project": pid,
                     "pages": json.loads(pages) if pages else None, "file": files.get(fk)})
    counts = dict(con.execute("SELECT project_id, COUNT(DISTINCT name) FROM tokens GROUP BY project_id").fetchall())
    projects = [{"id": pid, "name": name, "created_at": created,
                 "tokens": {"file": tf, "loaded_at": tl, "count": counts.get(pid, 0)},
                 "files": len({s["file_key"] for s in srcs if s["project"] == pid})}
                for pid, name, created, tf, tl in con.execute(
                    "SELECT id, name, created_at, tokens_file, tokens_loaded_at FROM projects ORDER BY id")]
    return {"projects": projects, "sources": srcs, "job": JOB.snapshot(), "figma_token": bool(read_token()),
            "settings": {"workers": workers(con)}}


def _project(con, value) -> int:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        raise ValueError("Choose a project")
    if not con.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone():
        raise ValueError("This project no longer exists")
    return pid


def add_source(con, url: str, pages, project) -> dict:
    pid = _project(con, project)
    key, node = rules.parse_link(url)
    pats = [p.strip() for p in (pages or []) if p and p.strip()] or None
    with dbm.writing(con):
        con.execute("INSERT OR IGNORE INTO sources (url, file_key, node_id, pages, added_at, project_id)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (url.strip(), key, node, json.dumps(pats) if pats else None, _now(), pid))
    return {"file_key": key}


_FILE_TABLES = ("nodes", "paints", "pages", "files", "snapshots", "components", "props", "effects", "images")


def _drop_orphans(con, keys) -> None:
    """Данные файла уходят, только если на него больше не ведёт ни одна ссылка ни в одном проекте."""
    for fk in set(keys):
        if not con.execute("SELECT 1 FROM sources WHERE file_key = ?", (fk,)).fetchone():
            for table in _FILE_TABLES:
                con.execute(f"DELETE FROM {table} WHERE file_key = ?", (fk,))


def remove_source(con, sid: int) -> None:
    with dbm.writing(con):
        row = con.execute("SELECT file_key FROM sources WHERE id = ?", (sid,)).fetchone()
        if not row:
            return
        con.execute("DELETE FROM sources WHERE id = ?", (sid,))
        _drop_orphans(con, [row[0]])


def update_source_pages(con, sid: int, pages) -> None:
    pats = [p.strip() for p in (pages or []) if p and p.strip()] or None
    with dbm.writing(con):
        con.execute("UPDATE sources SET pages = ? WHERE id = ?", (json.dumps(pats) if pats else None, sid))


def create_project(con, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Enter a project name")
    with dbm.writing(con):
        pid = con.execute("INSERT INTO projects (name, created_at) VALUES (?, ?)", (name[:80], _now())).lastrowid
    return {"id": pid}


def rename_project(con, project, name: str) -> None:
    pid = _project(con, project)
    name = (name or "").strip()
    if not name:
        raise ValueError("Enter a project name")
    with dbm.writing(con):
        con.execute("UPDATE projects SET name = ? WHERE id = ?", (name[:80], pid))


def remove_project(con, project) -> None:
    pid = _project(con, project)
    with dbm.writing(con):
        keys = [r[0] for r in con.execute("SELECT file_key FROM sources WHERE project_id = ?", (pid,))]
        con.execute("DELETE FROM sources WHERE project_id = ?", (pid,))
        con.execute("DELETE FROM tokens WHERE project_id = ?", (pid,))
        con.execute("DELETE FROM snapshots WHERE file_key = ?", (f"p:{pid}",))
        con.execute("DELETE FROM projects WHERE id = ?", (pid,))
        _drop_orphans(con, keys)


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "coloro"

    def log_message(self, fmt, *args):      # тишина в терминале: запросы — не новость
        pass

    # --- проверки ---

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True                      # запрос не из браузера или со своей страницы
        port = self.server.server_address[1]
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    # --- ответы ---

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, message: str, code: int = 400):
        self._json({"error": message}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20_000_000:
            raise ValueError("The request is too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    # --- маршруты ---

    def do_GET(self):
        if not self._host_ok():
            return self._error("Requests are accepted from this computer only", 403)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path.startswith("/api/"):
            con = dbm.connect(DB_PATH)
            try:
                return self._get(con, u.path, q)
            except ValueError as e:
                return self._error(str(e))
            except FigmaError as e:
                return self._error(str(e), 502)
            finally:
                con.close()
        return self._static(u.path)

    def _get(self, con, path: str, q: dict):
        filt = Filter.from_query(q)
        idx = tokens.load(con, filt.project)
        flat = {k: v[0] for k, v in q.items()}
        if path == "/api/state":
            return self._json(state(con))
        if path == "/api/overview":
            return self._json(health.overview(con, filt, idx))
        fkey = [filt.to_dict(), idx.sig]

        def remember(name, compute, *extra):
            return memo.cached(con, name, fkey + list(extra), compute)

        if path == "/api/colours":
            items = remember("colours", lambda: inventory.colours(con, filt, idx))
            st = inventory.stray(items)
            return self._json({"tokens": bool(idx), "items": items,
                               "counts": {k: len(v) for k, v in st.items()}})
        if path == "/api/gradients":
            return self._json({"items": remember("gradients", lambda: inventory.gradients(con, filt))})
        if path == "/api/tokens/usage":
            items = remember("colours", lambda: inventory.colours(con, filt, idx))
            return self._json({"items": tokens.usage(idx, items)})
        limit = max(1, min(5000, int(flat.get("limit") or 60)))
        if path in ("/api/places", "/api/screens"):
            c = flat.get("color", "").upper()
            a = int(flat.get("alpha") or 100)
            off = int(flat.get("offset") or 0)
            if path == "/api/screens":
                return self._json(inventory.screens(con, filt, c, a, limit=limit, offset=off))
            return self._json(inventory.places(con, filt, c, a, offset=off, file_key=flat.get("file_key"),
                                               screen=flat.get("screen")))
        if path == "/api/find":
            return self._json(search.find(con, filt, q, limit=limit, offset=int(flat.get("offset") or 0)))
        if path == "/api/find/layers":
            cond, args, _ = search.build(con, q)
            return self._json(search.layers(con, filt, cond, args, flat.get("file_key", ""), flat.get("screen") or None))
        if path == "/api/search":
            kind = flat.get("kind", "text")
            if kind == "colour":
                items = remember("colours", lambda: inventory.colours(con, filt, idx))
                return self._json({"items": search.colour_matches(items, flat.get("hex", ""), float(flat.get("tol") or 3))})
            cond, args, info = search.condition(kind, flat, con)
            if flat.get("file_key"):
                return self._json(search.layers(con, filt, cond, args, flat["file_key"], flat.get("screen") or None))
            phrase = norm(flat.get("q", "")) if kind == "text" else None
            res = search.screens(con, filt, cond, args, limit=limit, offset=int(flat.get("offset") or 0), rank_phrase=phrase,
                                 label="COALESCE(n.text, n.name)" if kind == "text" else "n.name")
            res.update(info)
            return self._json(res)
        if path == "/api/texts":
            return self._json(search.texts(con, filt, flat.get("q", ""), flat.get("mode", "forms"),
                                           limit=max(1, min(5000, int(flat.get("limit") or 500))),
                                           cat=flat.get("cat", "all"), sort=flat.get("sort", "uses")))
        if path == "/api/typography":
            return self._json(remember("typography", lambda: typography.fonts(con, filt)))
        if path == "/api/components":
            cq = flat.get("q", "")
            return self._json(remember("components", lambda: search.components(con, filt, cq), cq))
        if path == "/api/detached":
            return self._json(remember("detached", lambda: search.detached(con, filt)))
        if path == "/api/scales":
            return self._json(remember("scales", lambda: scales.report(con, filt)))
        if path == "/api/effects":
            return self._json(remember("effects", lambda: effects.report(con, filt)))
        if path == "/api/images":
            return self._json(remember("images", lambda: effects.images(con, filt)))
        if path == "/api/history":
            return self._json({"points": health.history(con, filt.project)})
        if path == "/api/export":
            html = remember("export", lambda: report.build(con, filt, idx))
            name = f"coloro-report-{datetime.now().strftime('%Y-%m-%d')}.html"
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        if path == "/api/previews":
            fk = flat.get("file_key", "")
            if not con.execute("SELECT 1 FROM files WHERE file_key = ?", (fk,)).fetchone():
                return self._error("Unknown file", 404)
            ids = [i for i in flat.get("ids", "").split(",") if i][:200]
            return self._json({"urls": previews(fk, ids)})
        if path == "/api/image-urls":
            fk = flat.get("file_key", "")
            if not con.execute("SELECT 1 FROM files WHERE file_key = ?", (fk,)).fetchone():
                return self._error("Unknown file", 404)
            return self._json({"urls": image_urls(fk)})
        return self._error("Not found", 404)

    def do_POST(self):
        if not self._host_ok() or not self._origin_ok():
            return self._error("Requests are accepted from this page only", 403)
        u = urlparse(self.path)
        try:
            body = self._body()
        except ValueError:
            return self._error("The request body could not be read")
        con = dbm.connect(DB_PATH)
        try:
            return self._post(con, u.path, body)
        except (ValueError, rules.LinkError, tokens.TokensError) as e:
            return self._error(str(e))
        finally:
            con.close()

    def _post(self, con, path: str, body: dict):
        if path == "/api/projects":
            return self._json(create_project(con, body.get("name", "")))
        if path == "/api/projects/rename":
            rename_project(con, body.get("id"), body.get("name", ""))
            return self._json({"ok": True})
        if path == "/api/projects/remove":
            remove_project(con, body.get("id"))
            return self._json({"ok": True})
        if path == "/api/sources":
            return self._json(add_source(con, body.get("url", ""), body.get("pages"), body.get("project")))
        if path == "/api/sources/remove":
            remove_source(con, int(body.get("id")))
            return self._json({"ok": True})
        if path == "/api/sources/pages":
            update_source_pages(con, int(body.get("id")), body.get("pages"))
            return self._json({"ok": True})
        if path == "/api/update":
            if not read_token():
                return self._error("Add a Figma access token in Settings first")
            rows = con.execute("SELECT file_key, pages, project_id FROM sources").fetchall()
            pid = body.get("project")
            if pid is not None:
                rows = [r for r in rows if r[2] == int(pid)]
            only = body.get("file_key")
            if only:
                rows = [r for r in rows if r[0] == only]
            if not rows:
                return self._error("Nothing to update. Add a Figma file first.")
            srcs = [{"file_key": fk, "pages": json.loads(p) if p else None} for fk, p, _ in rows]
            # Снимки — у всех проектов, где есть эти файлы: файл может быть в нескольких.
            keys = {r[0] for r in rows}
            projects = sorted({p for fk, _, p in con.execute("SELECT file_key, pages, project_id FROM sources")
                               if fk in keys and p is not None})
            if not JOB.start(srcs, bool(body.get("force")), projects, workers(con)):
                return self._error("An update is already running", 409)
            return self._json({"ok": True})
        if path == "/api/stop":
            JOB.stop.set()
            return self._json({"ok": True})
        if path == "/api/tokens":
            pid = _project(con, body.get("project"))
            rows = tokens.parse(body.get("text", ""), body.get("filename", ""))
            n = tokens.store(con, rows, body.get("filename") or "tokens", pid)
            return self._json({"count": n, "names": len({r[0] for r in rows})})
        if path == "/api/figma-token":
            save_token(body.get("token", ""))
            return self._json({"ok": True})
        if path == "/api/settings":
            try:
                n = max(1, min(8, int(body.get("workers"))))
            except (TypeError, ValueError):
                raise ValueError("Parallel downloads must be a number from 1 to 8")
            with dbm.writing(con):
                con.execute("INSERT OR REPLACE INTO meta VALUES ('workers', ?)", (str(n),))
            return self._json({"ok": True})
        return self._error("Not found", 404)

    def _static(self, path: str):
        name = "index.html" if path in ("", "/") else path.lstrip("/")
        f = (STATIC / name).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            return self._error("Not found", 404)
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)


def serve(port: int = PORT, open_browser: bool = True) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"coloro: {url}  (press Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
