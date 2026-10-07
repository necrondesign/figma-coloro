# -*- coding: utf-8 -*-
"""Сканер цветов в макетах Figma.

Запуск:
    python3 scan.py                        — все файлы из allfiles.json
    python3 scan.py <ссылка> [<ссылка>...] — только эти файлы

Какие страницы брать — задаётся в settings.json (pageFilter), по умолчанию "stage".
Пустое значение — все страницы. Архивные пропускаются всегда.
Собирает: плоские цвета (заливки и обводки), цвета-стопы градиентов,
число применений и примеры слоёв со ссылками.
Только GET-запросы. В макеты ничего не пишется.
"""
import json, os, re, sys, time, subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
RAW, OUT = BASE + "/raw", BASE + "/out"
def read_token():
    """Токен ищется по очереди: переменная окружения, файл рядом с инструментом,
    общий файл в ~/.config. Первый найденный выигрывает."""
    env = os.environ.get("FIGMA_TOKEN")
    if env and env.strip():
        return env.strip()
    for path in (BASE + "/token.txt",
                 os.path.expanduser("~/.config/coloro/token"),
                 os.path.expanduser("~/.config/figma-colors/token")):
        try:
            t = open(path, encoding="utf-8").read().strip()
            if t:
                return t
        except OSError:
            pass
    sys.stderr.write(
        "No Figma token found. Do one of these:\n"
        "  - put the token in token.txt next to this tool;\n"
        "  - or in ~/.config/figma-colors/token;\n"
        "  - or set the FIGMA_TOKEN environment variable.\n"
        "Create one in Figma: Settings - Security - Personal access tokens.\n")
    raise SystemExit(2)

TOK = read_token()

TARGET_NODES = 80000
BIG_BYTES = 210 * 1024 * 1024
SAMPLES_PER_PAGE = 20          # сколько слоёв запоминать на цвет внутри одной страницы

def page_pattern():
    """Какие страницы обходить. Пустая строка — все. Регистр не важен.
    Берётся из settings.json, по умолчанию «stage»."""
    try:
        return (json.load(open(BASE + "/settings.json", encoding="utf-8")).get("pageFilter") or "").strip()
    except Exception:
        return "stage"

PATTERN = page_pattern()

def page_matches(name):
    if not PATTERN:
        return True
    return PATTERN.lower() in (name or "").lower()

def filter_tag():
    """Метка фильтра для имени файла результата: обходы с разными фильтрами
    должны лежать рядом, а не затирать друг друга."""
    t = re.sub(r"[^a-z0-9]+", "-", (PATTERN or "all").lower()).strip("-")
    return t or "all"

def is_archive(name):
    s = (name or "").lower()
    return any(t in s for t in ("arhive", "archive", "архив", "arсhive"))

def parse_link(s):
    """Из ссылки Figma достаёт ключ файла и, если есть, node-id."""
    m = re.search(r"figma\.com/(?:file|design|proto)/([A-Za-z0-9]+)", s)
    key = m.group(1) if m else (s if re.fullmatch(r"[A-Za-z0-9]{10,}", s.strip()) else None)
    nid = None
    m2 = re.search(r"node-id=([0-9A-Za-z%:-]+)", s)
    if m2:
        nid = m2.group(1).replace("%3A", ":").replace("-", ":")
    return key, nid

def fetch(url, dest, tries=7):
    for i in range(tries):
        r = subprocess.run(["curl", "-sS", "--compressed", "-H", "X-Figma-Token: " + TOK,
                            "-o", dest, "-w", "%{http_code} %{size_download}",
                            "--max-time", "1800", url], capture_output=True, text=True)
        p = (r.stdout or "").split()
        code, size = (p[0] if p else "000"), (int(p[1]) if len(p) > 1 else 0)
        if code == "200":
            return size
        if code == "429":
            time.sleep(30 * (i + 1)); continue
        if code in ("500", "502", "503", "504", "000"):
            time.sleep(15 * (i + 1)); continue
        sys.stderr.write("HTTP %s %s\n" % (code, url[:110]))
        return -1
    return -1

def api_nodes(fkey, ids, depth=None):
    u = "https://api.figma.com/v1/files/%s/nodes?ids=%s" % (fkey, ",".join(ids))
    return u + ("&depth=%d" % depth if depth else "")

def ckey(c, mul):
    a = float(c.get("a", 1.0)) * mul
    h = "#%02X%02X%02X" % (int(round(c.get("r", 0) * 255)),
                           int(round(c.get("g", 0) * 255)),
                           int(round(c.get("b", 0) * 255)))
    pa = int(round(a * 100))
    return h if pa >= 100 else "%s@%d%%" % (h, pa)

GRADS = ("GRADIENT_LINEAR", "GRADIENT_RADIAL", "GRADIENT_ANGULAR", "GRADIENT_DIAMOND")

def new_page_acc():
    # key -> {"flat":n,"grad":n,"raw":n,"ex":[[id,name,type,slot],...]}
    return {}

def new_grad_acc():
    # "#A→#B" -> {"n":сколько раз, "type":вид градиента, "ex":[[id,name,slot],...]}
    return {}

def ent(acc, k):
    e = acc.get(k)
    if e is None:
        e = {"flat": 0, "grad": 0, "raw": 0, "ex": []}
        acc[k] = e
    return e

def walk(doc, acc, counters, grads):
    stack = [doc]
    while stack:
        n = stack.pop()
        counters["nodes"] += 1
        nid = n.get("id") or ""
        nname = n.get("name") or ""
        ntype = n.get("type") or ""
        bv = n.get("boundVariables") or {}
        sty = n.get("styles") or {}
        for field, slot in (("fills", "fill"), ("strokes", "stroke")):
            paints = n.get(field)
            if not isinstance(paints, list) or not paints:
                continue
            bvlist = bv.get(field) or []
            if field == "fills":
                has_style = bool(sty.get("fill") or sty.get("fills") or sty.get("text"))
            else:
                has_style = bool(sty.get("stroke") or sty.get("strokes"))
            for i, p in enumerate(paints):
                if not isinstance(p, dict) or p.get("visible") is False:
                    continue
                op = float(p.get("opacity", 1.0))
                t = p.get("type")
                bound = has_style or (i < len(bvlist) and bool(bvlist[i]))
                keys = []
                if t == "SOLID":
                    c = p.get("color")
                    if c:
                        keys = [(ckey(c, op), "flat")]
                elif t in GRADS:
                    seen, recipe = [], []
                    for s in (p.get("gradientStops") or []):
                        c = s.get("color")
                        if c:
                            k = ckey(c, 1.0)
                            recipe.append(k)
                            if k not in seen:
                                seen.append(k)
                    keys = [(k, "grad") for k in seen]
                    if recipe:
                        rk = "\u2192".join(recipe)
                        g = grads.get(rk)
                        if g is None:
                            g = {"n": 0, "type": t, "ex": []}
                            grads[rk] = g
                        g["n"] += 1
                        if len(g["ex"]) < SAMPLES_PER_PAGE and nid:
                            g["ex"].append([nid, nname[:60], slot])
                for k, kind in keys:
                    e = ent(acc, k)
                    e[kind] += 1
                    if not bound:
                        e["raw"] += 1
                    if len(e["ex"]) < SAMPLES_PER_PAGE and nid:
                        e["ex"].append([nid, nname[:60], ntype, slot])
        ch = n.get("children")
        if ch:
            for c in ch:
                stack.append(c)

def process(path, acc, counters, grads):
    with open(path, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    for nid, entry in (d.get("nodes") or {}).items():
        if entry and entry.get("document"):
            walk(entry["document"], acc, counters, grads)
    del d

def children_ids(fkey, nid, tmp):
    """Список прямых детей узла. Временный файл убираем за собой — иначе они копятся в raw/."""
    if fetch(api_nodes(fkey, [nid], depth=1), tmp) <= 0:
        return []
    try:
        d = json.load(open(tmp, encoding="utf-8"))
    except Exception:
        return []
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    e = (d.get("nodes") or {}).get(nid) or {}
    return [c["id"] for c in ((e.get("document") or {}).get("children") or []) if c.get("id")]

def fetch_group(fkey, ids, acc, counters, grads, tmp, depth=0):
    if not ids:
        return
    sz = fetch(api_nodes(fkey, ids), tmp)
    if sz < 0:
        if len(ids) == 1 and depth < 4:
            kids = children_ids(fkey, ids[0], tmp + ".c")
            if kids:
                for i in range(0, len(kids), 4):
                    fetch_group(fkey, kids[i:i+4], acc, counters, tmp, depth+1)
                return
        counters["errors"].append("download failed: %s" % (ids[:2],)); return
    if sz > BIG_BYTES and depth < 5:
        if len(ids) > 1:
            h = len(ids) // 2
            fetch_group(fkey, ids[:h], acc, counters, grads, tmp, depth+1)
            fetch_group(fkey, ids[h:], acc, counters, grads, tmp, depth+1)
            return
        kids = children_ids(fkey, ids[0], tmp + ".c")
        if kids:
            for i in range(0, len(kids), 3):
                fetch_group(fkey, kids[i:i+3], acc, counters, tmp, depth+1)
            return
    try:
        process(tmp, acc, counters, grads)
    except MemoryError:
        counters["errors"].append("out of memory: %s" % (ids[:2],))
    except ValueError:
        # Ответ оборвался на середине — JSON не разбирается. Это та же беда, что и
        # «слишком большой кусок»: дробим и качаем заново. Раньше это роняло весь файл.
        try:
            os.remove(tmp)
        except OSError:
            pass
        if depth < 5:
            if len(ids) > 1:
                h = len(ids) // 2
                fetch_group(fkey, ids[:h], acc, counters, grads, tmp, depth + 1)
                fetch_group(fkey, ids[h:], acc, counters, grads, tmp, depth + 1)
                return
            kids = children_ids(fkey, ids[0], tmp + ".c")
            if kids:
                for i in range(0, len(kids), 3):
                    fetch_group(fkey, kids[i:i+3], acc, counters, grads, tmp, depth + 1)
                return
        counters["errors"].append("truncated response: %s" % (ids[:2],))
        return
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

def do_file(fkey, only_node=None, force=False):
    # Разные срезы одного файла лежат в разных файлах результата: обход всего файла и обход
    # одной страницы не затирают друг друга. report.py потом склеивает их по страницам.
    if only_node:
        # Явная ссылка на страницу — фильтр к ней не применялся, метка не нужна.
        outp = "%s/%s__%s.json" % (OUT, fkey, only_node.replace(":", "-"))
    else:
        outp = "%s/%s@%s.json" % (OUT, fkey, filter_tag())
    # Явно переданную ссылку всегда пересобираем: человек дал её, чтобы получить свежие цифры.
    if os.path.exists(outp) and not force:
        sys.stderr.write("already collected, skipping: %s\n" % fkey); return
    tmp0 = "%s/%s.d1.json" % (RAW, fkey)
    if fetch("https://api.figma.com/v1/files/%s?depth=1" % fkey, tmp0) <= 0:
        sys.stderr.write("could not open file %s\n" % fkey); return
    d1 = json.load(open(tmp0, encoding="utf-8"))
    fname = d1.get("name") or fkey
    pages = [c for c in d1["document"]["children"] if c.get("type") == "CANVAS"]
    os.remove(tmp0)
    res = {"file": fname, "key": fkey, "filter": PATTERN, "pages": [], "skipped": [], "errors": [], "nodes": 0}
    t0 = time.time()
    # если в ссылке был node-id — слушаемся ссылки и фильтр по Stage не применяем
    if only_node:
        match = [pg for pg in pages if pg["id"] == only_node]
        if match:
            targets = [(pg["id"], pg.get("name") or "") for pg in match]
        else:
            # Не страница — значит фрейм или секция. Проверяем, что узел вообще существует,
            # иначе молча соберём пустышку и она попадёт в отчёт лишней строкой.
            probe = "%s/%s_probe.json" % (RAW, fkey)
            nm = None
            if fetch(api_nodes(fkey, [only_node], depth=1), probe) > 0:
                try:
                    pd = json.load(open(probe, encoding="utf-8"))
                    doc = ((pd.get("nodes") or {}).get(only_node) or {}).get("document")
                    if doc:
                        nm = doc.get("name") or only_node
                except Exception:
                    nm = None
                try:
                    os.remove(probe)
                except OSError:
                    pass
            if not nm:
                sys.stderr.write("BAD LINK: file %s has no node %s — check the node-id\n" % (fname, only_node))
                return
            targets = [(only_node, nm)]
    else:
        targets = []
        for pg in pages:
            pnm = pg.get("name") or ""
            if not page_matches(pnm) or is_archive(pnm):
                res["skipped"].append(pnm); continue
            targets.append((pg["id"], pnm))
    for pid, pnm in targets:
        acc = new_page_acc()
        grads = new_grad_acc()
        counters = {"nodes": 0, "errors": []}
        tmp = "%s/%s_%s.json" % (RAW, fkey, pid.replace(":", "-"))
        kids = children_ids(fkey, pid, tmp + ".c")
        if not kids:
            fetch_group(fkey, [pid], acc, counters, grads, tmp)
        else:
            for i in range(0, len(kids), 10):      # по 10 веток, крупные ответы режутся дальше сами
                fetch_group(fkey, kids[i:i+10], acc, counters, grads, tmp)
        res["pages"].append({"id": pid, "name": pnm, "nodes": counters["nodes"],
                             "colors": acc, "grads": grads})
        res["errors"] += counters["errors"]
        res["nodes"] += counters["nodes"]
        sys.stderr.write("  %-20s %-28s layers=%d colors=%d %.0fs\n"
                         % (fname[:20], pnm[:28], counters["nodes"], len(acc), time.time()-t0))
        sys.stderr.flush()
    # Пустой результат не сохраняем: он ничего не добавит, зато засорит отчёт лишней строкой.
    if not res["nodes"]:
        sys.stderr.write("EMPTY %-24s nothing found, result not saved\n" % fname)
        return
    json.dump(res, open(outp, "w", encoding="utf-8"), ensure_ascii=False)
    sys.stderr.write("DONE %-24s pages=%d layers=%d %.0fs\n"
                     % (fname, len(res["pages"]), res["nodes"], time.time()-t0))
    sys.stderr.flush()

if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        # Ссылку дали руками — значит хотят свежий результат, кэш не спасает.
        targets = []
        for a in args:
            k, n = parse_link(a)
            if k:
                targets.append((k, n, True))
            else:
                sys.stderr.write("not a Figma link: %s\n" % a)
    else:
        allf = json.load(open(BASE + "/allfiles.json", encoding="utf-8"))
        targets = [(f["key"], None, False) for f in allf]
    for k, n, force in targets:
        try:
            do_file(k, n, force)
        except Exception as ex:
            import traceback; traceback.print_exc()
            sys.stderr.write("FAILED %s %s\n" % (k, ex))
