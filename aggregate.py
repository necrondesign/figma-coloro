# -*- coding: utf-8 -*-
"""Склейка результатов scan.py в единый набор данных: цвета, градиенты, токены, сводка."""
import json, os, csv, colorsys, collections, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = BASE + "/out"
# Справочник токенов кита — необязателен. Поддерживаются два вида:
#   tokens.json  — выгрузка переменных плагином (например кнопкой Tokens в Booster);
#   путь к CSV   — задаётся в settings.json ключом tokensCsv.
TOKENS_JSON = BASE + "/tokens.json"
TOP_PAGES = 10
SAMPLES = 20

FAMS = ["Neutral","White","Black","Red","Orange","Yellow","Green","Teal","Blue","Purple","Magenta"]
FAM_RU = {f: f for f in FAMS}      # display names; kept as a map so the UI can be localised

def settings():
    try:
        return json.load(open(BASE + "/settings.json", encoding="utf-8"))
    except Exception:
        return {}

def tokens_from_json():
    """Выгрузка переменных плагином: список записей с именем и значениями по режимам."""
    rows, byval = [], collections.defaultdict(list)
    if not os.path.exists(TOKENS_JSON):
        return None
    try:
        data = json.load(open(TOKENS_JSON, encoding="utf-8"))
    except Exception:
        return None
    items = data.get("variables") if isinstance(data, dict) else data
    for it in items or []:
        nm = (it.get("name") or "").strip()
        if not nm:
            continue
        vals = it.get("values") or it.get("valuesByMode") or {}
        hexes = []
        for v in (vals.values() if isinstance(vals, dict) else vals):
            v = str(v).strip().upper()
            if v.startswith("#"):
                hexes.append(v)
        if not hexes:
            v = str(it.get("value") or "").strip().upper()
            if v.startswith("#"):
                hexes.append(v)
        if not hexes:
            continue
        rows.append({"name": nm, "v1": hexes[0], "v2": hexes[1] if len(hexes) > 1 else "",
                     "lib": it.get("library") or "", "col": it.get("collection") or "",
                     "shelf": it.get("shelf") or ""})
        for v in hexes[:2]:
            if nm not in byval[v]:
                byval[v].append(nm)
    rows.sort(key=lambda x: x["name"])
    return rows, byval

def token_table():
    """Имя токена -> значение и обратный индекс значение -> имена.
    Если справочника нет, вкладка «Токены» просто остаётся пустой."""
    j = tokens_from_json()
    if j:
        return j
    rows, byval = [], collections.defaultdict(list)
    p = settings().get("tokensCsv") or ""
    if not p or not os.path.exists(p):
        return rows, byval
    # Legacy CSV export with Russian column names; kept for backwards compatibility.
    for r in csv.DictReader(open(p, encoding="utf-8-sig"), delimiter=";"):
        if r.get("Тип") != "COLOR":
            continue
        nm = (r.get("Имя") or "").strip()
        if not nm or nm.startswith("неопознанн") or nm.startswith("локальная"):
            continue
        v1 = (r.get("Главное значение") or "").strip().upper()
        v2 = (r.get("Второе значение") or "").strip().upper()
        if not v1.startswith("#"):
            continue
        rows.append({"name": nm, "v1": v1, "v2": v2 if v2.startswith("#") else "",
                     "lib": r.get("Библиотека") or "", "col": r.get("Коллекция") or "",
                     "shelf": r.get("Полка") or ""})
        for v in (v1, v2):
            if v.startswith("#") and nm not in byval[v]:
                byval[v].append(nm)
    rows.sort(key=lambda x: x["name"])
    return rows, byval

def hsl(hexs):
    r, g, b = (int(hexs[i:i+2], 16) / 255.0 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360.0, s, l

def fam_of(h, s, l):
    if s <= 0.08:
        if l >= 0.93: return "White"
        if l <= 0.12: return "Black"
        return "Neutral"
    if h < 14 or h >= 330: return "Red"
    for hi, nm in ((42,"Orange"),(70,"Yellow"),(157,"Green"),(196,"Teal"),(248,"Blue"),(288,"Purple"),(330,"Magenta")):
        if h < hi: return nm
    return "Red"

def scanned_slices(page_filter=None):
    """Все срезы из out/, по одному разу на страницу — из самого свежего файла."""
    best, per_source = {}, {}
    for fn in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
        if not fn.endswith(".json"):
            continue
        path = OUT + "/" + fn
        mt = os.path.getmtime(path)
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        key = d.get("key")
        if not key:
            continue
        node = fn[:-5].split("__")[1].replace("-", ":") if "__" in fn else None
        sid = key + ("|" + node if node else "")
        per_source[sid] = {"key": key, "node": node, "name": d.get("file") or key,
                           "at": mt, "pages": len(d.get("pages") or []),
                           "nodes": d.get("nodes", 0), "skipped": d.get("skipped") or [],
                           "errors": len(d.get("errors") or []), "file": fn}
        for pg in d.get("pages") or []:
            if page_filter and page_filter.lower() not in (pg.get("name") or "").lower():
                continue
            pk = (key, pg["id"])
            prev = best.get(pk)
            if prev is None or mt >= prev[0]:
                best[pk] = (mt, d.get("file") or key, pg)
    return best, per_source

def build(page_filter=None):
    """page_filter — показать только страницы, в имени которых есть эта строка."""
    tok_rows, tok_by_val = token_table()
    best, per_source = scanned_slices(page_filter)

    files, pages, fidx, pidx = [], [], {}, {}
    colors, grads = {}, {}
    stats = {"nodes": 0, "pages": 0, "errors": 0, "skipped": collections.Counter()}

    for (key, _pid), (_mt, fname, pg) in sorted(best.items(), key=lambda kv: (kv[1][1], kv[0][1])):
        if key not in fidx:
            fidx[key] = len(files); files.append([key, fname])
        pk = (key, pg["id"])
        if pk not in pidx:
            pidx[pk] = len(pages); pages.append([fidx[key], pg["id"], pg["name"]])
        pi = pidx[pk]
        stats["pages"] += 1
        stats["nodes"] += pg.get("nodes", 0)
        for ck, e in (pg.get("colors") or {}).items():
            c = colors.get(ck)
            if c is None:
                c = {"flat":0,"grad":0,"raw":0,"pages":[],"files":set()}; colors[ck] = c
            c["flat"] += e["flat"]; c["grad"] += e["grad"]; c["raw"] += e["raw"]
            c["files"].add(key)
            c["pages"].append([pi, e["flat"] + e["grad"], [[x[0], x[1], x[3]] for x in e["ex"][:SAMPLES]]])
        for rk, g in (pg.get("grads") or {}).items():
            gg = grads.get(rk)
            if gg is None:
                gg = {"n":0,"type":g.get("type",""),"pages":[],"files":set()}; grads[rk] = gg
            gg["n"] += g["n"]; gg["files"].add(key)
            gg["pages"].append([pi, g["n"], [[x[0], x[1], x[2]] for x in (g.get("ex") or [])[:SAMPLES]]])
    for src in per_source.values():
        stats["errors"] += src["errors"]
        for s in src["skipped"]:
            stats["skipped"][s] += 1

    crows = []
    for ck, c in colors.items():
        hexs = ck.split("@")[0]
        alpha = int(ck.split("@")[1].rstrip("%")) if "@" in ck else 100
        h, s, l = hsl(hexs)
        c["pages"].sort(key=lambda p: -p[1])
        crows.append({"k": ck, "x": hexs, "a": alpha, "f": fam_of(h, s, l),
                      "t": c["flat"] + c["grad"], "fl": c["flat"], "gr": c["grad"], "rw": c["raw"],
                      "nf": len(c["files"]),
                      "tk": tok_by_val.get(ck if alpha != 100 else hexs) or [],
                      "p": c["pages"][:TOP_PAGES], "more": max(0, len(c["pages"]) - TOP_PAGES),
                      "_l": l, "_h": h})
    crows.sort(key=lambda r: -r["t"])

    grows = []
    for rk, g in grads.items():
        g["pages"].sort(key=lambda p: -p[1])
        stops = rk.split("→")
        grows.append({"r": rk, "s": stops, "n": g["n"], "ty": g["type"].replace("GRADIENT_", ""),
                      "nf": len(g["files"]), "ns": len(stops),
                      "p": g["pages"][:TOP_PAGES], "more": max(0, len(g["pages"]) - TOP_PAGES)})
    grows.sort(key=lambda r: -r["n"])

    used = {c["k"] for c in crows}
    used_hex = {c["k"].split("@")[0] for c in crows}
    trows = []
    for t in tok_rows:
        hits = [c["t"] for c in crows if c["k"] == t["v1"] or (t["v2"] and c["k"] == t["v2"])]
        trows.append({"name": t["name"], "v1": t["v1"], "v2": t["v2"], "lib": t["lib"],
                      "col": t["col"], "shelf": t["shelf"],
                      "used": bool(hits), "n": sum(hits)})

    return {
        "files": files, "pages": pages, "colors": crows, "grads": grows, "tokens": trows,
        "fams": FAMS, "famru": FAM_RU,
        "sources": sorted(per_source.values(), key=lambda s: s["name"]),
        "stats": {
            "files": len(files), "pages": stats["pages"], "nodes": stats["nodes"],
            "errors": stats["errors"], "colors": len(crows), "grads": len(grows),
            "uses": sum(c["t"] for c in crows),
            "flat": sum(c["fl"] for c in crows), "gradUses": sum(c["gr"] for c in crows),
            "raw": sum(c["rw"] for c in crows),
            "gradOnly": len([c for c in crows if c["gr"] and not c["fl"]]),
            "flatOnly": len([c for c in crows if c["fl"] and not c["gr"]]),
            "both": len([c for c in crows if c["fl"] and c["gr"]]),
            "withToken": len([c for c in crows if c["tk"]]),
            "rare": len([c for c in crows if c["t"] <= 10]),
            "tokensTotal": len(trows), "tokensUsed": len([t for t in trows if t["used"]]),
            "skipped": stats["skipped"].most_common(30),
        },
        "pageFilter": page_filter or "",
        "built": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
