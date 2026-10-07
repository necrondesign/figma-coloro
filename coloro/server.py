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
from . import effects, health, inventory, memo, rules, scales, search, tokens, typography
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
        raise ValueError("нужен токен Figma — его можно задать в настройках")
    with _IMAGE_GATE:
        with _IMAGE_LOCK:
            got = _IMAGE_URLS.get(file_key)       # пока ждали очереди, мог принести другой запрос
            if got and time.time() - got[0] < _IMAGE_TTL:
                return got[1]
        urls = (Figma(token).get_json(f"/files/{file_key}/images").get("meta") or {}).get("images") or {}
    with _IMAGE_LOCK:
        _IMAGE_URLS[file_key] = (time.time(), urls)
    return urls


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
        raise ValueError("токен слишком короткий — скопируйте его целиком")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_PATH.with_name(TOKEN_PATH.name + ".tmp")
    tmp.write_text(clean, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(TOKEN_PATH)


# ---------------------------------------------------------------- обновление

class Job:
    """Одно обновление в фоне. Прогресс читает страница, остановить можно в любой момент."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.state = {"running": False}

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state))

    def start(self, sources: list[dict], force: bool) -> bool:
        with self.lock:
            if self.state.get("running"):
                return False
            self.stop.clear()
            self.state = {"running": True, "started": _now(), "files_total": len({s["file_key"] for s in sources}),
                          "files_done": 0, "current": {}, "reports": []}
        threading.Thread(target=self._run, args=(sources, force), daemon=True).start()
        return True

    def _progress(self, **kw):
        with self.lock:
            self.state.setdefault("current", {})[kw.get("file") or ""] = {
                "page": kw.get("page"), "index": kw.get("index"), "total": kw.get("total")}

    def _run(self, sources, force):
        reports = []
        try:
            reports = update_all(DB_PATH, read_token(), sources, workers=4, force=force,
                                 stop=self.stop, progress=self._progress)
        except Exception as e:     # noqa: BLE001 — любая ошибка должна дойти до экрана, а не умереть в потоке
            reports = [{"status": "failed", "error": str(e)}]
        # Снимок для стрелок «лучше или хуже» — только если что-то действительно загрузилось.
        if any(r.get("pages_loaded") for r in reports):
            con = dbm.connect(DB_PATH)
            try:
                health.snapshot(con, tokens.load(con))
            finally:
                con.close()
        with self.lock:
            self.state.update(running=False, finished=_now(), reports=reports, current={},
                              files_done=len(reports), stopped=self.stop.is_set())


JOB = Job()


# ---------------------------------------------------------------- данные для страниц

def state(con) -> dict:
    srcs = [dict(zip(("id", "url", "file_key", "node_id", "pages", "added_at"), r))
            for r in con.execute("SELECT id, url, file_key, node_id, pages, added_at FROM sources ORDER BY id")]
    files = {}
    for fk, name, ver, lm, checked, loaded, fmt in con.execute(
            "SELECT file_key, name, version, last_modified, checked_at, loaded_at, format FROM files"):
        files[fk] = {"name": name, "version": ver, "last_modified": lm, "checked_at": checked,
                     "loaded_at": loaded, "outdated_format": fmt != dbm.FORMAT, "pages": []}
    for fk, pid, name, archived, status, error, nodes, loaded in con.execute(
            "SELECT file_key, page_id, name, archived, status, error, nodes, loaded_at FROM pages"
            " ORDER BY file_key, position"):
        if fk in files:
            files[fk]["pages"].append({"id": pid, "name": name, "archived": bool(archived), "status": status,
                                       "error": error, "nodes": nodes, "loaded_at": loaded})
    for s in srcs:
        s["pages"] = json.loads(s["pages"]) if s["pages"] else None
        s["file"] = files.get(s["file_key"])
    tok = dict(con.execute("SELECT k, v FROM meta WHERE k LIKE 'tokens_%'").fetchall())
    count = con.execute("SELECT COUNT(DISTINCT name) FROM tokens").fetchone()[0]
    return {"sources": srcs, "job": JOB.snapshot(), "figma_token": bool(read_token()),
            "tokens": {"file": tok.get("tokens_file"), "loaded_at": tok.get("tokens_loaded_at"), "count": count}}


def add_source(con, url: str, pages) -> dict:
    key, node = rules.parse_link(url)
    pats = [p.strip() for p in (pages or []) if p and p.strip()] or None
    with dbm.writing(con):
        con.execute("INSERT OR IGNORE INTO sources (url, file_key, node_id, pages, added_at) VALUES (?, ?, ?, ?, ?)",
                    (url.strip(), key, node, json.dumps(pats) if pats else None, _now()))
    return {"file_key": key}


def remove_source(con, sid: int) -> None:
    with dbm.writing(con):
        row = con.execute("SELECT file_key FROM sources WHERE id = ?", (sid,)).fetchone()
        if not row:
            return
        con.execute("DELETE FROM sources WHERE id = ?", (sid,))
        # Данные файла уходят, только если на него больше не ведёт ни одна ссылка.
        if not con.execute("SELECT 1 FROM sources WHERE file_key = ?", row).fetchone():
            for table in ("nodes", "paints", "pages", "files", "snapshots", "components", "props", "effects", "images"):
                con.execute(f"DELETE FROM {table} WHERE file_key = ?", row)


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

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, message: str, code: int = 400):
        self._json({"error": message}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20_000_000:
            raise ValueError("слишком большой запрос")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    # --- маршруты ---

    def do_GET(self):
        if not self._host_ok():
            return self._error("запрос не с этого компьютера", 403)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path.startswith("/api/"):
            con = dbm.connect(DB_PATH)
            try:
                filt = Filter.from_query(q)
                idx = tokens.load(con)
                if u.path == "/api/state":
                    return self._json(state(con))
                if u.path == "/api/overview":
                    return self._json(health.overview(con, filt, idx))
                fkey = [filt.to_dict(), idx.sig]

                def remember(name, compute, *extra):
                    return memo.cached(con, name, fkey + list(extra), compute)

                if u.path == "/api/colours":
                    items = remember("colours", lambda: inventory.colours(con, filt, idx))
                    st = inventory.stray(items)
                    return self._json({"tokens": bool(idx), "items": items,
                                       "counts": {k: len(v) for k, v in st.items()}})
                if u.path in ("/api/places", "/api/screens"):
                    c = (q.get("color") or [""])[0].upper()
                    a = int((q.get("alpha") or ["100"])[0])
                    off = int((q.get("offset") or ["0"])[0])
                    if u.path == "/api/screens":
                        return self._json(inventory.screens(con, filt, c, a, offset=off))
                    fk = (q.get("file_key") or [None])[0]
                    sc = (q.get("screen") or [None])[0]
                    return self._json(inventory.places(con, filt, c, a, offset=off, file_key=fk, screen=sc))
                if u.path == "/api/search":
                    flat = {k: v[0] for k, v in q.items()}
                    kind = flat.get("kind", "text")
                    if kind == "colour":
                        items = remember("colours", lambda: inventory.colours(con, filt, idx))
                        return self._json({"items": search.colour_matches(items, flat.get("hex", ""), float(flat.get("tol") or 3))})
                    cond, args, info = search.condition(kind, flat, con)
                    if flat.get("file_key"):
                        return self._json(search.layers(con, filt, cond, args, flat["file_key"], flat.get("screen") or None))
                    phrase = norm(flat.get("q", "")) if kind == "text" else None
                    res = search.screens(con, filt, cond, args, offset=int(flat.get("offset") or 0), rank_phrase=phrase,
                                         label="COALESCE(n.text, n.name)" if kind == "text" else "n.name")
                    res.update(info)
                    return self._json(res)
                if u.path == "/api/typography":
                    return self._json(remember("typography", lambda: typography.fonts(con, filt)))
                if u.path == "/api/components":
                    cq = (q.get("q") or [""])[0]
                    return self._json(remember("components", lambda: search.components(con, filt, cq), cq))
                if u.path == "/api/detached":
                    return self._json(remember("detached", lambda: search.detached(con, filt)))
                if u.path == "/api/scales":
                    return self._json(remember("scales", lambda: scales.report(con, filt)))
                if u.path == "/api/effects":
                    return self._json(remember("effects", lambda: effects.report(con, filt)))
                if u.path == "/api/images":
                    return self._json(remember("images", lambda: effects.images(con, filt)))
                if u.path == "/api/image-urls":
                    fk = (q.get("file_key") or [""])[0]
                    if not con.execute("SELECT 1 FROM files WHERE file_key = ?", (fk,)).fetchone():
                        return self._error("нет такого файла", 404)
                    return self._json({"urls": image_urls(fk)})
                return self._error("нет такого адреса", 404)
            except ValueError as e:
                return self._error(str(e))
            except FigmaError as e:
                return self._error(str(e), 502)
            finally:
                con.close()
        return self._static(u.path)

    def do_POST(self):
        if not self._host_ok() or not self._origin_ok():
            return self._error("запрос не с этой страницы", 403)
        u = urlparse(self.path)
        try:
            body = self._body()
        except ValueError:
            return self._error("тело запроса не разбирается")
        con = dbm.connect(DB_PATH)
        try:
            if u.path == "/api/sources":
                return self._json(add_source(con, body.get("url", ""), body.get("pages")))
            if u.path == "/api/sources/remove":
                remove_source(con, int(body.get("id")))
                return self._json({"ok": True})
            if u.path == "/api/update":
                if not read_token():
                    return self._error("сначала задайте токен Figma в настройках")
                srcs = [{"file_key": fk, "pages": json.loads(p) if p else None}
                        for fk, p in con.execute("SELECT file_key, pages FROM sources")]
                only = body.get("file_key")
                if only:
                    srcs = [s for s in srcs if s["file_key"] == only]
                if not srcs:
                    return self._error("нечего обновлять — добавьте ссылку на файл")
                if not JOB.start(srcs, bool(body.get("force"))):
                    return self._error("обновление уже идёт", 409)
                return self._json({"ok": True})
            if u.path == "/api/stop":
                JOB.stop.set()
                return self._json({"ok": True})
            if u.path == "/api/tokens":
                rows = tokens.parse(body.get("text", ""), body.get("filename", ""))
                n = tokens.store(con, rows, body.get("filename") or "справочник")
                return self._json({"count": n, "names": len({r[0] for r in rows})})
            if u.path == "/api/figma-token":
                save_token(body.get("token", ""))
                return self._json({"ok": True})
            return self._error("нет такого адреса", 404)
        except (ValueError, rules.LinkError, tokens.TokensError) as e:
            return self._error(str(e))
        finally:
            con.close()

    def _static(self, path: str):
        name = "index.html" if path in ("", "/") else path.lstrip("/")
        f = (STATIC / name).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            return self._error("нет такой страницы", 404)
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)


def serve(port: int = PORT, open_browser: bool = True) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"coloro: {url}  (остановить — Ctrl+C)", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
