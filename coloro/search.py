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
from . import fuzzy, memo
from .textnorm import norm, query_stems

_CONS = set("бвгджзйклмнпрстфхцчшщ")


def _patterns(stem: str) -> list[str]:
    """Шаблоны для одной основы. Беглая гласная: у «кнопк» есть «кнопок», у «окн» — «окон»,
    поэтому, если основа кончается на две согласные, допускаем гласную между ними."""
    pats = [f"%{stem}%"]
    if len(stem) >= 3 and stem[-1] in _CONS and stem[-2] in _CONS:
        pats.append(f"%{stem[:-1]}_{stem[-1]}%")
    return pats


def _all_words(column: str, stems: list) -> tuple[str, list]:
    """Все слова запроса в столбце. Слово — основа или список: своя основа и запасные варианты."""
    parts, args = [], []
    for s in stems:
        pats = [p for x in ([s] if isinstance(s, str) else s) for p in _patterns(x)]
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
            raise SearchError("Enter a word or phrase")
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
            raise SearchError("Width, height and tolerance must be numbers")
        if not w and not h:
            raise SearchError("Enter a width, a height or both")
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
            raise SearchError("Unknown font")
        return "n.type = 'TEXT' AND n.tstyle IS NULL AND n.pinst IS NULL AND n.font = ?", [fid], {}

    if kind == "component":
        cid = q.get("component")
        if cid:
            return "n.type = 'INSTANCE' AND n.comp = ?", [cid], {}
        # Набор и компонент — по имени: у одного и того же набора в разных файлах разные id,
        # а дизайнер ищет «все кнопки», где бы они ни лежали.
        sname, cname, variant = q.get("set"), q.get("cname"), q.get("variant")
        if not (sname or cname):
            raise SearchError("Choose a component")
        if con is None:
            raise SearchError("A database is required")
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
    if kind == "textexact":
        # Один и тот же текст во всех местах — по нормализованному тексту целиком.
        value = norm(q.get("text") or "")
        if not value:
            raise SearchError("Choose a text")
        return "n.type = 'TEXT' AND n.tnorm = ?", [value], {}

    if kind == "gradient":
        try:
            gid = int(q.get("grad") or 0)
        except ValueError:
            raise SearchError("Unknown gradient")
        return "(n.file_key, n.id) IN (SELECT file_key, node_id FROM paints WHERE grad = ?)", [gid], {}
    if kind == "image":
        from . import effects
        c, a = effects.image_condition(q)
        return c, a, {}

    raise SearchError("Unknown search type")


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
                      "screen": names.get((fk, screen)) or "No screen",
                      "screen_id": screen, "count": count, "first_seen": first,
                      "layers": layer_names[:4], "more_layers": max(0, len(layer_names) - 4),
                      "link": figma_link(fk, screen)})
    return {"total": len(rows), "total_places": total_places, "items": items, "limit": limit, "offset": offset}


def layers(con, filt: Filter, cond: str, args: list, file_key: str, screen: str | None,
           limit: int = 200) -> dict:
    """Слои одного экрана, на которых нашлось."""
    where, fargs = filt.where()
    base = (" FROM nodes n" + NODE_JOIN + " LEFT JOIN vals sv ON sv.id = n.sect LEFT JOIN vals fv ON fv.id = n.font"
            f" WHERE {where} AND {cond} AND n.file_key = ?")
    params = fargs + args + [file_key]
    if screen:
        base += " AND n.screen = ?"
        params.append(screen)
    else:
        base += " AND n.screen IS NULL"
    total = con.execute("SELECT COUNT(*)" + base, params).fetchone()[0]
    rows = con.execute(
        "SELECT n.id, n.name, n.type, n.text, sv.v, n.anchor, n.hid, n.w, n.h, n.ovr, n.page_id, fv.v" + base +
        " ORDER BY n.name LIMIT ?", params + [limit]).fetchall()
    # Цвета слоя — для подробностей при наведении. Одним запросом на страницу слоёв.
    fills: dict[str, list] = {}
    by_page: dict[str, list[str]] = {}
    for r in rows:
        by_page.setdefault(r[10], []).append(r[0])
    for pid, ids in by_page.items():
        for nid, slot, kind, c, a, src in con.execute(
                "SELECT node_id, slot, kind, color, alpha, src FROM paints WHERE file_key = ? AND page_id = ?"
                f" AND node_id IN ({','.join('?' * len(ids))})", [file_key, pid, *ids]):
            fills.setdefault(nid, []).append({"slot": slot, "kind": kind, "color": c, "alpha": a,
                                              "source": "style" if (src or "").startswith("s:") else "variable" if src == "v" else "manual"})
    from .typography import label as font_label, parse as font_parse
    items = []
    for nid, name, ntype, text, sect, anchor, hid, w, h, ovr, _pid, font in rows:
        items.append({"node_id": nid, "name": name, "type": ntype,
                      "font": font_label(font_parse(font)) if font else "", "paints": fills.get(nid, [])[:6],
                      "text": (text or "")[:140], "sections": sect or "", "hidden": bool(hid),
                      "size": f"{(w or 0) / 10:g} × {(h or 0) / 10:g}" if w is not None else "",
                      "overridden": bool(ovr), "link": figma_link(file_key, anchor or screen),
                      "exact_link": anchor == nid})
    return {"total": total, "items": items}


def colour_matches(items: list[dict], hexv: str, tol: float) -> list[dict]:
    """Цвета из учёта, похожие на заданный: разница по CIEDE2000 не больше допуска."""
    parsed = colorm.parse(hexv)
    if not parsed:
        raise SearchError("Color must look like #RRGGBB")
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
        # Перечень экранов, а не их число: у набора экраны считаются по всем вариантам вместе —
        # экран, где стоят две разные кнопки одного набора, — это один экран, а не два.
        " COUNT(*), SUM(n.ovr), GROUP_CONCAT(DISTINCT n.screen), MAX(n.screen IS NULL),"
        # Образец для превью: видимый инстанс, поставленный на экран напрямую, а не вложенный в
        # другой инстанс, — такой слой Figma умеет нарисовать отдельной картинкой. Сначала без
        # изменений (тексты и цвета как в компоненте), иначе любой.
        " COALESCE(MIN(CASE WHEN n.hid = 0 AND IFNULL(n.ovr, 0) = 0 AND instr(n.id, ';') = 0 AND n.id NOT LIKE 'I%' THEN n.id END),"
        " MIN(CASE WHEN n.hid = 0 AND instr(n.id, ';') = 0 AND n.id NOT LIKE 'I%' THEN n.id END))"
        " FROM nodes n" + NODE_SCAN +
        " LEFT JOIN components c ON c.file_key = n.file_key AND c.id = n.comp"
        f" WHERE n.type = 'INSTANCE' AND {where}"
        # «+n.comp» — группировка выражением, а не колонкой: иначе SQLite идёт по индексу
        # компонентов и ищет каждый слой по ключу — на 4,3 млн слоёв 3,8 с вместо 1,2.
        " GROUP BY n.file_key, +n.comp", fargs).fetchall()
    sets: dict[str, dict] = {}
    # Свой компонент лежит в файле — рисуем его самого: это эталон, без правок инстанса.
    local = set()
    for fk, cid in {(r[0], r[1]) for r in rows if r[1]}:
        if con.execute("SELECT 1 FROM nodes WHERE file_key = ? AND id = ? AND type = 'COMPONENT'", (fk, cid)).fetchone():
            local.add((fk, cid))
    for fk, cid, name, sid, sname, remote, count, ovr, scr_list, no_screen, sample in rows:
        title = sname or name or "Untitled"
        key = f"set:{sname}" if sname else f"c:{name or cid}"
        if qn and qn not in norm(title) and qn not in norm(name or ""):
            continue
        g = sets.setdefault(key, {"title": title, "set": sname, "cname": None if sname else (name or ""),
                                  "remote": bool(remote),
                                  "instances": 0, "overridden": 0, "screens": set(), "files": set(),
                                  "variants": {}, "components": []})
        g["instances"] += count
        g["overridden"] += ovr or 0
        g["screens"].update((fk, s) for s in (scr_list or "").split(",") if s)
        if no_screen:
            g["screens"].add((fk, None))
        g["files"].add(fk)
        preview = [fk, cid] if (fk, cid) in local else [fk, sample] if sample else None
        g["components"].append({"id": cid, "file_key": fk, "name": name or "", "count": count,
                                "props": variant_props(name or ""), "preview": preview})
        for k, v in variant_props(name or "").items():
            g["variants"].setdefault(k, {}).setdefault(v, 0)
            g["variants"][k][v] += count
    out = []
    for g in sets.values():
        g["files"] = len(g["files"])
        g["screens"] = len(g["screens"])
        g["components"].sort(key=lambda c: -c["count"])
        g["preview"] = next((c["preview"] for c in g["components"] if c["preview"]), None)
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


# ---------------------------------------------------------------- поиск всем сразу

# Типы слоёв, как их видит дизайнер. В фильтре «тип» — эти группы, а не внутренние имена Figma.
TYPE_GROUPS = {
    "text": ("TEXT",),
    "frame": ("FRAME", "GROUP", "SECTION"),
    "instance": ("INSTANCE",),
    "component": ("COMPONENT", "COMPONENT_SET"),
    "shape": ("RECTANGLE", "ELLIPSE", "VECTOR", "LINE", "POLYGON", "STAR", "BOOLEAN_OPERATION", "REGULAR_POLYGON"),
}
_GROUP_OF = {t: g for g, ts in TYPE_GROUPS.items() for t in ts}


def _one(q: dict, k: str) -> str:
    v = q.get(k)
    if isinstance(v, list):
        v = v[0] if v else ""
    return (v or "").strip() if isinstance(v, str) else ""


def _many(q: dict, k: str) -> list[str]:
    v = q.get(k)
    if v is None:
        return []
    vals = v if isinstance(v, list) else [v]
    return [x for x in vals if isinstance(x, str) and x.strip()]


def _components_where(con, sql: str, args: list) -> dict[str, list[str]]:
    by_file: dict[str, list[str]] = {}
    for fk, cid in con.execute("SELECT file_key, id FROM components WHERE " + sql, args):
        by_file.setdefault(fk, []).append(cid)
    return by_file


def _instances_of(by_file: dict[str, list[str]]) -> tuple[str, list]:
    """Инстансы этих компонентов. Пары «файл, компонент» — одной таблицей значений: цепочка
    «или» по каждому файлу проверялась бы на каждом слое и при сотне компонентов тормозила."""
    pairs = [(fk, cid) for fk, ids in by_file.items() for cid in ids]
    if not pairs:
        return "0", []
    return ("n.type = 'INSTANCE' AND (n.file_key, n.comp) IN (VALUES " + ",".join("(?, ?)" for _ in pairs) + ")",
            [x for p in pairs for x in p])


def _fuzzy(con, project, text: str, typos: bool, layout: bool) -> tuple[list, list[str]]:
    """Слова запроса с запасными вариантами из словаря проекта (см. fuzzy)."""
    if not (typos or layout):
        return query_stems(text), []
    vocab = memo.cached(con, "vocabulary", [project], lambda: fuzzy.vocabulary(con, project))
    return memo.cached(con, "expand", [project, norm(text), typos, layout],
                       lambda: fuzzy.expand(text, vocab, typos, layout))


def _flag(q: dict, name: str, default: bool) -> bool:
    v = _one(q, name)
    return default if v in (None, "") else v in ("1", "true", "on")


def build(con, q: dict, project: int | None = None) -> tuple[str, list, dict]:
    """Запрос из нескольких частей → одно условие на слои. Части складываются через «и»:
    текст «Купить» + размер 56×56 + цвет #FF006F — кнопки с этим текстом, размером и цветом."""
    parts, args, info = [], [], {}

    text = _one(q, "q")
    if text:
        # Где искать — несколько мест сразу: надписи, названия слоёв, компонентов, страниц и файлов.
        where = {w for w in _many(q, "where") if w in ("text", "name", "component", "page")}
        if not where or "all" in _many(q, "where"):
            where = {"text", "name", "component"}
        # Как совпадать: «forms» — слова в любой форме и в любом порядке; «exact» — фраза целиком,
        # как написана (без учёта регистра и «ё»).
        exact = _one(q, "mode") == "exact"
        whole = _one(q, "whole") in ("1", "true", "on")
        # Запасные слова: опечатки (по желанию) и другая раскладка с транслитом (по умолчанию).
        stems, also = _fuzzy(con, project, text, not exact and _flag(q, "typos", False),
                             not exact and _flag(q, "layout", True))
        if not stems:
            raise SearchError("Enter a word or phrase")
        phrase = norm(text)
        spec = ("x:" + phrase) if exact else ("f:" + ",".join("|".join([s] if isinstance(s, str) else s) for s in stems))

        def match(column):
            if exact:
                c, a = f"{column} LIKE ?", [f"%{phrase}%"]
            else:
                c, a = _all_words(column, stems)
            if whole:
                # Сначала быстрый отбор по вхождению, затем проверка целыми словами.
                return f"({c} AND whole_words({column}, ?))", a + [spec]
            return c, a
        ors, oargs = [], []
        if "text" in where:
            c, a = match("n.tnorm")
            ors.append(f"(n.type = 'TEXT' AND {c})")
            oargs += a
        if "name" in where:
            c, a = match("n.nnorm")
            ors.append(f"({c})")
            oargs += a
        if "component" in where:
            # Название компонента или набора: «кнопка» находит все инстансы кнопок.
            c, a = match("norm(IFNULL(set_name, '') || ' ' || IFNULL(name, ''))")
            ic, ia = _instances_of(_components_where(con, c, a))
            if ic != "0":
                ors.append(f"({ic})")
                oargs += ia
        if "page" in where:
            # Название страницы или файла: находятся экраны на этой странице или в этом файле.
            cp, ap = match("norm(pg.name)")
            cf, af = match("norm(f.name)")
            ors.append(f"(n.id = n.screen AND ({cp} OR {cf}))")
            oargs += ap + af
        if not ors:
            ors.append("0")
        parts.append("(" + " OR ".join(ors) + ")")
        args += oargs
        info["stems"] = [s if isinstance(s, str) else s[0] for s in stems]
        if also:
            info["also"] = also
        info["phrase"] = norm(text)

    w, h = _one(q, "w"), _one(q, "h")
    if w or h:
        c, a, _ = condition("size", {"w": w, "h": h, "tol": _one(q, "tol")})
        parts.append(c)
        args += a

    colour = _one(q, "color")
    if colour:
        parsed = colorm.parse(colour)
        if not parsed:
            raise SearchError("Color must look like #RRGGBB or #RRGGBBAA")
        c, a = parsed
        with_alpha = len(colour.lstrip("#")) == 8 or "rgba" in colour.lower()
        try:
            tol = float(_one(q, "ctol") or 3)
        except ValueError:
            raise SearchError("Color tolerance must be a number")
        lab = colorm.lab(c)
        values = [(vc, va) for vc, va in con.execute("SELECT DISTINCT color, alpha FROM paints")
                  if vc and colorm.de2000(lab, colorm.lab(vc)) <= tol and (not with_alpha or abs(va - a) <= 5)]
        if values:
            parts.append("(n.file_key, n.id) IN (SELECT file_key, node_id FROM paints WHERE (color, alpha) IN (VALUES "
                         + ",".join("(?, ?)" for _ in values) + "))")
            args += [x for v in values for x in v]
        else:
            parts.append("0")
        info["colours"] = len(values)

    types = [t for t in _many(q, "type") if t in TYPE_GROUPS]
    if types:
        names = [n for t in types for n in TYPE_GROUPS[t]]
        parts.append(f"n.type IN ({','.join('?' * len(names))})")
        args += names

    pages = _many(q, "page")
    if pages:
        parts.append(f"pg.name IN ({','.join('?' * len(pages))})")
        args += pages

    comps = _many(q, "comp")
    props = {k[5:]: _many(q, k) for k in q if k.startswith("prop_") and _many(q, k)}
    if comps or props:
        sql, sargs = [], []
        if comps:
            sql.append(f"IFNULL(set_name, name) IN ({','.join('?' * len(comps))})")
            sargs += comps
        for prop, values in props.items():
            # Значение свойства — как в имени варианта «Size=B, Color=Pink».
            sql.append("(" + " OR ".join("(', ' || name || ',') LIKE ?" for _ in values) + ")")
            sargs += [f"%, {prop}={v},%" for v in values]
        c, a = _instances_of(_components_where(con, " AND ".join(sql), sargs))
        parts.append(c)
        args += a

    font = _one(q, "font")
    if font:
        c, a, _ = condition("font", {"font": font})
        parts.append(c)
        args += a

    if not parts:
        raise SearchError("Enter text, a size or a color")
    return " AND ".join(parts), args, info


def find(con, filt: Filter, q: dict, limit: int = 60, offset: int = 0) -> dict:
    """Поиск всем сразу: экраны с совпадениями и фильтры по найденному — тип, страница, файл,
    компонент, свойства вариантов — со счётом. Один проход по слоям."""
    cond, args, info = build(con, q, filt.project)
    where, fargs = filt.where()
    phrase = info.get("phrase")
    rank = "SUM(instr(IFNULL(n.tnorm, '') || ' ' || IFNULL(n.nnorm, ''), ?) > 0)" if phrase else "0"
    rows = con.execute(
        f"SELECT n.file_key, n.screen, n.type, n.page_id, n.comp, COUNT(*), MIN(n.first_seen), {rank},"
        " MAX(f.name), MAX(pg.name), MIN(pg.position),"
        " GROUP_CONCAT(DISTINCT replace(substr(COALESCE(n.text, n.name), 1, 80), ',', char(31)))"
        " FROM nodes n" + NODE_SCAN + f" WHERE {where} AND {cond}"
        " GROUP BY n.file_key, n.screen, n.type, n.page_id, +n.comp",
        ([phrase] if phrase else []) + fargs + args).fetchall()

    comp_info = {}
    if any(r[4] for r in rows):
        for fk, cid, name, sname in con.execute("SELECT file_key, id, name, set_name FROM components"):
            comp_info[(fk, cid)] = (sname or name or "Untitled", variant_props(name or "") if sname else {})

    screens: dict[tuple, dict] = {}
    facets = {"type": {}, "page": {}, "file": {}, "comp": {}, "props": {}}
    for fk, screen, ntype, _pid, comp, count, first, rk, fname, pname, pos, labels in rows:
        s = screens.get((fk, screen))
        if s is None:
            s = screens[(fk, screen)] = {"file_key": fk, "screen_id": screen, "file": fname, "page": pname,
                                         "pos": pos or 0, "count": 0, "rank": 0, "first_seen": first, "labels": set()}
        s["count"] += count
        s["rank"] += rk or 0
        if first and (not s["first_seen"] or first < s["first_seen"]):
            s["first_seen"] = first
        s["labels"].update(x.replace(chr(31), ",") for x in (labels or "").split(",") if x)
        g = _GROUP_OF.get(ntype, "other")
        facets["type"][g] = facets["type"].get(g, 0) + count
        facets["page"][pname] = facets["page"].get(pname, 0) + count
        facets["file"][fk] = facets["file"].get(fk, 0) + count
        if comp and (fk, comp) in comp_info:
            title, vp = comp_info[(fk, comp)]
            facets["comp"][title] = facets["comp"].get(title, 0) + count
            for k, v in vp.items():
                facets["props"].setdefault(k, {})
                facets["props"][k][v] = facets["props"][k].get(v, 0) + count

    ordered = sorted(screens.values(), key=lambda s: (-s["rank"], -s["count"], s["file"] or "", s["pos"], s["screen_id"] or ""))
    page = ordered[offset:offset + limit]
    items = []
    for s in page:
        name = None
        if s["screen_id"]:
            got = con.execute("SELECT name FROM nodes WHERE file_key = ? AND id = ?", (s["file_key"], s["screen_id"])).fetchone()
            name = got[0] if got else None
        labels = sorted(s["labels"])
        items.append({"file_key": s["file_key"], "file": s["file"], "page": s["page"], "screen": name or "No screen",
                      "screen_id": s["screen_id"], "count": s["count"], "first_seen": s["first_seen"],
                      "layers": labels[:4], "more_layers": max(0, len(labels) - 4),
                      "link": figma_link(s["file_key"], s["screen_id"])})

    def top(d, n=40):
        return [{"value": k, "count": v} for k, v in sorted(d.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n]]
    return {"total": len(ordered), "total_places": sum(s["count"] for s in ordered), "items": items,
            "limit": limit, "offset": offset, "info": info,
            "facets": {"type": top(facets["type"]), "page": top(facets["page"]), "file": top(facets["file"]),
                       "comp": top(facets["comp"]),
                       "props": {k: top(v, 20) for k, v in sorted(facets["props"].items())}}}


# ---------------------------------------------------------------- тексты

TEXT_CATS = {
    "all": lambda i: True,
    "repeated": lambda i: i["uses"] > 1,
    "once": lambda i: i["uses"] == 1,
    "variants": lambda i: i["variants"] > 1,
    "unstyled": lambda i: i["unstyled"] > 0,
}
TEXT_SORTS = {
    "uses": lambda i: (-i["uses"], i["key"]),
    "screens": lambda i: (-i["screens"], -i["uses"], i["key"]),
    "long": lambda i: (-len(i["key"]), i["key"]),
    "az": lambda i: i["key"],
}


def texts(con, filt: Filter, q: str = "", mode: str = "forms", limit: int = 500,
          cat: str = "all", sort: str = "uses", whole: bool = False,
          typos: bool = False, layout: bool = True) -> dict:
    """Все тексты макетов: одинаковый текст в разных местах — одна строка со счётом.

    Видно, какие формулировки повторяются, где одно и то же написано по-разному и какие тексты
    стоят без стиля. Одинаковыми считаются тексты, совпадающие без учёта регистра, «ё» и пробелов."""
    where, args = filt.where()
    cond, also = "", []
    if q:
        stems, also = _fuzzy(con, filt.project, q, typos and mode != "exact", layout and mode != "exact")
        if mode == "exact":
            cond, cargs = " AND n.tnorm LIKE ?", [f"%{norm(q)}%"]
            if whole:
                cond += " AND whole_words(n.tnorm, ?)"
                cargs.append("x:" + norm(q))
        elif stems:
            c, cargs = _all_words("n.tnorm", stems)
            cond = " AND " + c
            if whole:
                cond += " AND whole_words(n.tnorm, ?)"
                cargs.append("f:" + ",".join("|".join([s] if isinstance(s, str) else s) for s in stems))
        else:
            cargs = []
        args = args + cargs
    rows = con.execute(
        "SELECT n.tnorm, MIN(n.text), COUNT(*), COUNT(DISTINCT n.file_key || '|' || IFNULL(n.screen, '')),"
        " COUNT(DISTINCT n.file_key), SUM(n.tstyle IS NULL AND n.pinst IS NULL), SUM(n.pinst IS NOT NULL),"
        " MIN(n.first_seen), COUNT(DISTINCT n.text)"
        " FROM nodes n" + NODE_SCAN +
        f" WHERE {where} AND n.type = 'TEXT' AND n.tnorm IS NOT NULL AND n.tnorm != ''{cond}"
        " GROUP BY n.tnorm", args).fetchall()
    items = [{"key": key, "text": (text or "")[:300], "uses": uses, "screens": screens, "files": files,
              "unstyled": unstyled or 0, "in_instances": inst or 0, "first_seen": first, "variants": variants}
             for key, text, uses, screens, files, unstyled, inst, first, variants in rows]
    # Счёт по всем текстам, а не по показанной части: иначе редкие тексты за пределом списка
    # пропадали бы из счётчиков категорий.
    counts = {k: sum(1 for i in items if f(i)) for k, f in TEXT_CATS.items()}
    chosen = [i for i in items if TEXT_CATS.get(cat, TEXT_CATS["all"])(i)]
    chosen.sort(key=TEXT_SORTS.get(sort, TEXT_SORTS["uses"]))
    return {"total": len(items), "total_uses": sum(i["uses"] for i in items), "counts": counts,
            "matched": len(chosen), "items": chosen[:limit], "also": also}
