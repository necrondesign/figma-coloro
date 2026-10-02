# -*- coding: utf-8 -*-
"""Локальное приложение «Цвета макетов».

Поднимает страницу на http://localhost:8800 — список источников, кнопки обновления,
вкладки со сводкой, цветами, градиентами и токенами. Figma только читается.
"""
import json, os, re, sys, threading, subprocess, time, webbrowser, http.server, socketserver, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = BASE + "/out"
SRC = BASE + "/sources.json"
SET = BASE + "/settings.json"
PORT = 8800

sys.path.insert(0, BASE)
import aggregate  # noqa: E402

LOCK = threading.Lock()
JOB = {"active": False, "total": 0, "done": 0, "current": "", "log": [], "started": 0, "stop": False}

# Сборка данных стоит дорого: это чтение всех срезов из out/. Страница опрашивает
# состояние раз в 2,5 секунды, поэтому держим готовый результат и пересобираем его,
# только когда папка на самом деле изменилась.
CACHE = {}
CACHE_LOCK = threading.Lock()

def out_stamp():
    try:
        names = sorted(f for f in os.listdir(OUT) if f.endswith(".json"))
    except OSError:
        return ()
    return tuple((n, os.path.getmtime(OUT + "/" + n)) for n in names)

def build_cached(page_filter=None):
    key = page_filter or ""
    stamp = out_stamp()
    with CACHE_LOCK:
        hit = CACHE.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    data = aggregate.build(page_filter)
    with CACHE_LOCK:
        CACHE[key] = (stamp, data)
        if len(CACHE) > 8:          # разных срезов много не держим
            for k in list(CACHE)[:-8]:
                CACHE.pop(k, None)
    return data

def link_of(key, node=None):
    u = "https://www.figma.com/design/" + key
    return u + ("?node-id=" + node.replace(":", "-") if node else "")

def load_sources():
    if os.path.exists(SRC):
        try:
            return json.load(open(SRC, encoding="utf-8"))
        except Exception:
            pass
    # первый запуск: засеиваем списком файлов папки 2.1
    seed = []
    p = BASE + "/allfiles.json"
    if os.path.exists(p):
        for f in json.load(open(p, encoding="utf-8")):
            seed.append({"key": f["key"], "node": None, "name": f["name"], "link": link_of(f["key"])})
    save_sources(seed)
    return seed

def save_sources(lst):
    json.dump(lst, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def load_settings():
    try:
        d = json.load(open(SET, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("pageFilter", "stage")
    d.setdefault("workers", 6)
    return d

def save_settings(d):
    json.dump(d, open(SET, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def parse_link(s):
    m = re.search(r"figma\.com/(?:file|design|proto)/([A-Za-z0-9]+)", s or "")
    key = m.group(1) if m else (s.strip() if re.fullmatch(r"[A-Za-z0-9]{10,}", (s or "").strip()) else None)
    node = None
    m2 = re.search(r"node-id=([0-9A-Za-z%:-]+)", s or "")
    if m2:
        node = m2.group(1).replace("%3A", ":").replace("-", ":")
    return key, node

def sid_of(s):
    return s["key"] + ("|" + s["node"] if s.get("node") else "")

def scan_one(t):
    """Обход одной цели отдельным процессом. Возвращает строку для лога."""
    try:
        p = subprocess.run([sys.executable, BASE + "/scan.py", link_of(t["key"], t.get("node"))],
                           capture_output=True, text=True, cwd=BASE, timeout=3600)
        tail = [l for l in (p.stderr or "").strip().split("\n") if l.strip()][-1:]
        return tail[0].strip() if tail else "пусто"
    except subprocess.TimeoutExpired:
        return "timed out"
    except Exception as ex:
        return "failed: %s" % ex

def run_targets(targets):
    """Обходит цели в несколько потоков; прогресс кладёт в JOB.
    Потоки — это именно то, что ускоряет полный проход с получаса до нескольких минут."""
    workers = max(1, min(8, int(load_settings().get("workers") or 6)))
    with LOCK:
        JOB.update({"active": True, "total": len(targets), "done": 0,
                    "current": "%d sources, %d threads" % (len(targets), workers),
                    "log": [], "started": time.time(), "stop": False})

    queue = list(targets)
    qlock = threading.Lock()

    def worker():
        while True:
            with qlock:
                if not queue:
                    return
                t = queue.pop(0)
            with LOCK:
                if JOB["stop"]:
                    return
            line = scan_one(t)
            with LOCK:
                JOB["done"] += 1
                JOB["log"].append("%s — %s" % (t.get("name") or t["key"], line))
                JOB["log"] = JOB["log"][-80:]

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    with LOCK:
        JOB["active"] = False
        JOB["current"] = ""

def state():
    data = build_cached()
    by_sid = {}
    for s in data["sources"]:
        by_sid[s["key"] + ("|" + s["node"] if s.get("node") else "")] = s
    out = []
    for s in load_sources():
        st = by_sid.get(sid_of(s))
        out.append({
            "key": s["key"], "node": s.get("node"), "name": s.get("name") or s["key"],
            "link": s.get("link") or link_of(s["key"], s.get("node")),
            "scanned": bool(st),
            "pages": st["pages"] if st else 0,
            "nodes": st["nodes"] if st else 0,
            "at": time.strftime("%d.%m %H:%M", time.localtime(st["at"])) if st else "",
            "errors": st["errors"] if st else 0,
        })
    with LOCK:
        job = dict(JOB)
    return {"sources": out, "job": job, "stats": data["stats"], "built": data["built"],
            "settings": load_settings()}

class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = open(BASE + "/app.html", "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/state":
            return self._send(state())
        if path == "/api/data":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            pf = (q.get("pages") or [""])[0].strip()
            return self._send(build_cached(pf or None))
        if path == "/api/job":
            with LOCK:
                return self._send(dict(JOB))
        self.send_error(404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            body = {}

        if path == "/api/add":
            key, node = parse_link(body.get("link") or "")
            if not key:
                return self._send({"ok": False, "error": "That does not look like a Figma link"}, 400)
            lst = load_sources()
            new = {"key": key, "node": node, "name": body.get("name") or key,
                   "link": link_of(key, node)}
            if any(sid_of(s) == sid_of(new) for s in lst):
                return self._send({"ok": False, "error": "That source is already in the list"}, 400)
            lst.append(new); save_sources(lst)
            return self._send({"ok": True})

        if path == "/api/remove":
            lst = [s for s in load_sources() if sid_of(s) != (body.get("sid") or "")]
            save_sources(lst)
            return self._send({"ok": True})

        if path == "/api/refresh":
            with LOCK:
                if JOB["active"]:
                    return self._send({"ok": False, "error": "A crawl is already running"}, 409)
            lst = load_sources()
            want = body.get("sids")
            targets = lst if want in (None, "all") else [s for s in lst if sid_of(s) in want]
            if not targets:
                return self._send({"ok": False, "error": "Nothing to crawl"}, 400)
            threading.Thread(target=run_targets, args=(targets,), daemon=True).start()
            return self._send({"ok": True, "total": len(targets)})

        if path == "/api/settings":
            st = load_settings()
            if "pageFilter" in body:
                st["pageFilter"] = str(body.get("pageFilter") or "").strip()
            if "workers" in body:
                try:
                    st["workers"] = max(1, min(8, int(body.get("workers"))))
                except Exception:
                    pass
            save_settings(st)
            return self._send({"ok": True, "settings": st})

        if path == "/api/stop":
            with LOCK:
                JOB["stop"] = True
            return self._send({"ok": True})

        if path == "/api/export":
            try:
                subprocess.run([sys.executable, BASE + "/report.py"], cwd=BASE,
                               capture_output=True, text=True, timeout=600)
                return self._send({"ok": True, "file": "colors-report.html"})
            except Exception as ex:
                return self._send({"ok": False, "error": str(ex)}, 500)

        self.send_error(404)

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    load_sources()
    save_settings(load_settings())
    with Server(("127.0.0.1", PORT), H) as httpd:
        url = "http://localhost:%d/" % PORT
        print("Color Inventory is running at %s" % url)
        print("Press Ctrl+C here to stop it")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
