"""Поиск по макетам: текст, название слоя, размер, компонент, цвет.

Результат всегда одного вида — экраны, на которых нашлось, и сколько там; по экрану — сами
слои со ссылкой. Дизайнер думает экранами, а не слоями.

Текст ищется по основам слов: «купите монеты» находит «Купить 100 монет», слова — в любом
порядке. Название слоя ищется так же, поэтому текстовый слой находится и по тексту, и по имени.
"""

from __future__ import annotations

import re

from . import color as colorm
from .filters import NODE_JOIN, NODE_SCAN, Filter
from .inventory import figma_link
from .textnorm import norm, query_stems

_CONS = set("бвгджзйклмнпрстфхцчшщ")


def _patterns(stem: str) -> list[str]:
    """Шаблоны для одной основы. Беглая гласная: у «кнопк» есть «кнопок», у «окн» — «окон»,
    поэтому, если основа кончается на две согласные, допускаем гласную между ними."""
    pats = [f"%{stem}%"]
    if len(stem) >= 3 and stem[-1] in _CONS and stem[-2] in _CONS:
        pats.append(f"%{stem[:-1]}_{stem[-1]}%")
    return pats


def _all_words(column: str, stems: list[str]) -> tuple[str, list]:
    parts, args = [], []
    for s in stems:
        pats = _patterns(s)
        parts.append("(" + " OR ".join(f"{column} LIKE ?" for _ in pats) + ")")
        args += pats
    return " AND ".join(parts), args


class SearchError(ValueError):
    pass


def condition(kind: str, q: dict, con=None) -> tuple[str, list, dict]:
    """Запрос → условие на слои n, его аргументы и пояснение того, что именно ищется."""
    if kind == "text":
        stems = query_stems(q.get("q", ""))
        if not stems:
            raise SearchError("введите слово или фразу")
        where = (q.get("where") or "both")
        conds, args = [], []
        if where in ("both", "text"):
            c, a = _all_words("n.tnorm", stems)
            conds.append(f"(n.type = 'TEXT' AND {c})")
            args += a
        if where in ("both", "name"):
            c, a = _all_words("n.nnorm", stems)
            conds.append(f"({c})")
            args += a
        return "(" + " OR ".join(conds) + ")", args, {"stems": stems}

    if kind == "size":
        try:
            w = float(q.get("w") or 0)
            h = float(q.get("h") or 0)
            tol = float(q.get("tol") or 0)
        except ValueError:
            raise SearchError("ширина, высота и допуск — числа")
        if not w and not h:
            raise SearchError("задайте ширину, высоту или обе")
        conds, args = [], []
        # Размеры в базе — в десятых долях пикселя. Без допуска — точное совпадение до
        # пол-пикселя: 56 и 56,2 на экране не отличить.
        t = max(tol, 0.5) * 10
        if w:
            conds.append("n.w BETWEEN ? AND ?")
            args += [round(w * 10 - t), round(w * 10 + t)]
        if h:
            conds.append("n.h BETWEEN ? AND ?")
            args += [round(h * 10 - t), round(h * 10 + t)]
        only = q.get("type") or ""
        if only == "instance":
            conds.append("n.type = 'INSTANCE'")
        elif only == "frame":
            conds.append("n.type IN ('FRAME', 'COMPONENT', 'INSTANCE', 'GROUP')")
        elif only == "text":
            conds.append("n.type = 'TEXT'")
        return " AND ".join(conds), args, {}

    if kind == "font":
        # Тексты без стиля с этим сочетанием шрифта, положенные на экран вручную —
        # то же, что считает экран типографики.
        try:
            fid = int(q.get("font") or 0)
        except ValueError:
            raise SearchError("неизвестный шрифт")
        return "n.type = 'TEXT' AND n.tstyle IS NULL AND n.pinst IS NULL AND n.font = ?", [fid], {}

    if kind == "component":
        cid = q.get("component")
        if cid:
            return "n.type = 'INSTANCE' AND n.comp = ?", [cid], {}
        # Набор и компонент — по имени: у одного и того же набора в разных файлах разные id,
        # а дизайнер ищет «все кнопки», где бы они ни лежали.
        sname, cname, variant = q.get("set"), q.get("cname"), q.get("variant")
        if not (sname or cname):
            raise SearchError("выберите компонент")
        if con is None:
            raise SearchError("нужна база")
        # Сначала находим сами компоненты в маленькой таблице, потом их инстансы — по индексу.
        # Подзапрос прямо в условии выполнялся бы для каждого слоя: секунды вместо долей.
        sql = "SELECT file_key, id FROM components WHERE " + ("set_name = ?" if sname else "name = ? AND set_name IS NULL")
        sargs = [sname or cname]
        if variant and "=" in variant:
            # Значение свойства варианта: «Color=Pink» — как в имени варианта «Size=B, Color=Pink».
            sql += " AND (', ' || name || ',') LIKE ?"
            sargs.append(f"%, {variant.strip()},%")
        by_file: dict[str, list] = {}
        for fk, cid in con.execute(sql, sargs):
            by_file.setdefault(fk, []).append(cid)
        if not by_file:
            return "0", [], {}
        # id компонента уникален только внутри файла, поэтому условие — по каждому файлу.
        parts, args = [], []
        for fk, ids in by_file.items():
            parts.append(f"(n.file_key = ? AND n.comp IN ({','.join('?' * len(ids))}))")
            args += [fk, *ids]
        return "n.type = 'INSTANCE' AND (" + " OR ".join(parts) + ")", args, {}

    if kind == "prop":
        from . import scales
        c, a = scales.condition(q)
        return c, a, {}
    if kind == "effect":
        from . import effects
        c, a = effects.condition(q)
        return c, a, {}
    if kind == "image":
        from . import effects
        c, a = effects.image_condition(q)
        return c, a, {}

    raise SearchError("неизвестный вид поиска")


def screens(con, filt: Filter, cond: str, args: list, limit: int = 60, offset: int = 0,
            rank_phrase: str | None = None, label: str = "n.name") -> dict:
    """Экраны, на которых нашлось, со счётом. Сначала — где больше совпадений.

    label — что показывать в строке экрана. Для поиска по тексту это сам текст, а не название
    слоя: у текстового слоя название часто осталось от старой заглушки, а текст давно другой.

    Один проход по слоям: группы считаются сразу, итоги и страница результатов — уже из групп.
    Названия экранов ищутся только для показанной страницы."""
    where, fargs = filt.where()
    rank = "SUM(instr(IFNULL(n.tnorm, '') || ' ' || IFNULL(n.nnorm, ''), ?) > 0)" if rank_phrase else "0"
    rows = con.execute(
        f"SELECT n.file_key, n.screen, COUNT(*), MIN(n.first_seen), {rank}, MAX(f.name), MAX(pg.name),"
        f" MIN(pg.position), GROUP_CONCAT(DISTINCT replace(substr({label}, 1, 80), ',', char(31)))"
        " FROM nodes n" + NODE_SCAN + f" WHERE {where} AND {cond} GROUP BY n.file_key, n.screen",
        ([rank_phrase] if rank_phrase else []) + fargs + args).fetchall()
    total_places = sum(r[2] for r in rows)
    # Порядок: точное совпадение фразы, потом больше мест, потом файл и страница по порядку.
    rows.sort(key=lambda r: (-r[4], -r[2], r[5] or "", r[7] or 0, r[1] or ""))
    page = rows[offset:offset + limit]
    names = {}
    for fk, screen, *_ in page:
        if screen:
            got = con.execute("SELECT name FROM nodes WHERE file_key = ? AND id = ?", (fk, screen)).fetchone()
            names[(fk, screen)] = got[0] if got else None
    items = []
    for fk, screen, count, first, _rank, fname, pname, _pos, layer_list in page:
        layer_names = sorted({x.replace(chr(31), ",") for x in (layer_list or "").split(",") if x})
        items.append({"file_key": fk, "file": fname, "page": pname,
                      "screen": names.get((fk, screen)) or "без экрана",
                      "screen_id": screen, "count": count, "first_seen": first,
                      "layers": layer_names[:4], "more_layers": max(0, len(layer_names) - 4),
                      "link": figma_link(fk, screen)})
    return {"total": len(rows), "total_places": total_places, "items": items, "limit": limit, "offset": offset}


def layers(con, filt: Filter, cond: str, args: list, file_key: str, screen: str | None,
           limit: int = 200) -> dict:
    """Слои одного экрана, на которых нашлось."""
    where, fargs = filt.where()
    base = (" FROM nodes n" + NODE_JOIN + " LEFT JOIN vals sv ON sv.id = n.sect"
            f" WHERE {where} AND {cond} AND n.file_key = ?")
    params = fargs + args + [file_key]
    if screen:
        base += " AND n.screen = ?"
        params.append(screen)
    else:
        base += " AND n.screen IS NULL"
    total = con.execute("SELECT COUNT(*)" + base, params).fetchone()[0]
    rows = con.execute(
        "SELECT n.id, n.name, n.type, n.text, sv.v, n.anchor, n.hid, n.w, n.h, n.ovr" + base +
        " ORDER BY n.name LIMIT ?", params + [limit]).fetchall()
    items = []
    for nid, name, ntype, text, sect, anchor, hid, w, h, ovr in rows:
        items.append({"node_id": nid, "name": name, "type": ntype,
                      "text": (text or "")[:140], "sections": sect or "", "hidden": bool(hid),
                      "size": f"{(w or 0) / 10:g} × {(h or 0) / 10:g}" if w is not None else "",
                      "overridden": bool(ovr), "link": figma_link(file_key, anchor or screen),
                      "exact_link": anchor == nid})
    return {"total": total, "items": items}


def colour_matches(items: list[dict], hexv: str, tol: float) -> list[dict]:
    """Цвета из учёта, похожие на заданный: разница по CIEDE2000 не больше допуска."""
    parsed = colorm.parse(hexv)
    if not parsed:
        raise SearchError("цвет — в виде #RRGGBB")
    c, a = parsed
    lab = colorm.lab(c)
    out = []
    for i in items:
        de = colorm.de2000(lab, colorm.lab(i["color"]))
        if de <= tol and abs(i["alpha"] - a) <= max(5, tol * 2):
            out.append({**i, "de": round(de, 2)})
    out.sort(key=lambda i: (i["de"], -i["uses"]))
    return out


# ---------------------------------------------------------------- компоненты

_VARIANT = re.compile(r"\s*([^=,]+?)\s*=\s*([^,]+?)\s*(?:,|$)")


def variant_props(name: str) -> dict:
    """«Size=B, Color=Pink» → {"Size": "B", "Color": "Pink"}. У обычного компонента — пусто."""
    if "=" not in (name or ""):
        return {}
    return {k: v for k, v in _VARIANT.findall(name)}


def components(con, filt: Filter, q: str = "") -> dict:
    """Компоненты, которые используются в макетах: сколько инстансов, где, сколько изменено.

    Варианты одного набора собраны под набором, а их свойства («Size», «Color») — фильтры."""
    where, fargs = filt.where()
    qn = norm(q)
    rows = con.execute(
        "SELECT n.file_key, n.comp, c.name, c.set_id, c.set_name, c.remote,"
        " COUNT(*), SUM(n.ovr), COUNT(DISTINCT n.file_key || '|' || IFNULL(n.screen, ''))"
        " FROM nodes n" + NODE_SCAN +
        " LEFT JOIN components c ON c.file_key = n.file_key AND c.id = n.comp"
        f" WHERE n.type = 'INSTANCE' AND {where}"
        # «+n.comp» — группировка выражением, а не колонкой: иначе SQLite идёт по индексу
        # компонентов и ищет каждый слой по ключу — на 4,3 млн слоёв 3,8 с вместо 1,2.
        " GROUP BY n.file_key, +n.comp", fargs).fetchall()
    sets: dict[str, dict] = {}
    for fk, cid, name, sid, sname, remote, count, ovr, scr in rows:
        title = sname or name or "без названия"
        key = f"set:{sname}" if sname else f"c:{name or cid}"
        if qn and qn not in norm(title) and qn not in norm(name or ""):
            continue
        g = sets.setdefault(key, {"title": title, "set": sname, "cname": None if sname else (name or ""),
                                  "remote": bool(remote),
                                  "instances": 0, "overridden": 0, "screens": 0, "files": set(),
                                  "variants": {}, "components": []})
        g["instances"] += count
        g["overridden"] += ovr or 0
        g["screens"] += scr
        g["files"].add(fk)
        g["components"].append({"id": cid, "file_key": fk, "name": name or "", "count": count,
                                "props": variant_props(name or "")})
        for k, v in variant_props(name or "").items():
            g["variants"].setdefault(k, {}).setdefault(v, 0)
            g["variants"][k][v] += count
    out = []
    for g in sets.values():
        g["files"] = len(g["files"])
        g["components"].sort(key=lambda c: -c["count"])
        out.append(g)
    out.sort(key=lambda g: -g["instances"])
    return {"items": out, "total": len(out)}


def detached(con, filt: Filter, limit: int = 200) -> dict:
    """Похоже на отвязанные копии: кадр или группа, названные как компонент файла, но не инстанс.

    Когда инстанс отвязывают, получившийся кадр сохраняет имя компонента. Это эвристика —
    так же может называться и обычный кадр, — поэтому формулировка «похоже», а не «это»."""
    where, fargs = filt.where()
    # Имена компонентов нормализуем один раз и кладём во временную таблицу: если делать это
    # прямо в запросе, нормализация повторяется для каждого слоя — секунды вместо долей.
    names = set()
    for fk, name, sname in con.execute("SELECT file_key, name, set_name FROM components"):
        for x in (name, sname):
            if x:
                names.add((fk, norm(x)))
    con.execute("CREATE TEMP TABLE IF NOT EXISTS cnames (file_key TEXT, nm TEXT, PRIMARY KEY (file_key, nm)) WITHOUT ROWID")
    con.execute("DELETE FROM cnames")
    con.executemany("INSERT OR IGNORE INTO cnames VALUES (?, ?)", names)
    rows = con.execute(
        "SELECT n.file_key, f.name, pg.name, s.name, n.screen, n.id, n.name, n.anchor"
        " FROM nodes n" + NODE_SCAN +
        " JOIN cnames c ON c.file_key = n.file_key AND c.nm = n.nnorm"
        " LEFT JOIN nodes s ON s.file_key = n.file_key AND s.id = n.screen"
        f" WHERE n.type IN ('FRAME', 'GROUP') AND n.pinst IS NULL AND n.id != IFNULL(n.screen, '') AND {where}"
        " ORDER BY f.name, pg.position, s.name LIMIT ?", fargs + [limit]).fetchall()
    items = [{"file_key": fk, "file": fn, "page": pn, "screen": sn or "", "node_id": nid, "name": name,
              "link": figma_link(fk, anchor or nid)} for fk, fn, pn, sn, screen, nid, name, anchor in rows]
    return {"items": items, "total": len(items), "capped": len(items) >= limit}
