"""Справочник токенов дизайн-системы: любой распространённый формат.

Понимает:
- W3C Design Tokens — дерево с «$value» и «$type», ссылки вида «{color.brand.primary}»
- Tokens Studio — дерево с «value» и «type», ссылки так же
- выгрузку переменных: список записей с «name» и «value» / «values» / «valuesByMode»
- CSV с заголовком: колонка имени (name, token, имя) и одна или несколько колонок значений
  (value, hex, color, значение, «главное значение», «второе значение»…), разделитель любой

Токены с одинаковым значением не склеиваются: у одного значения может быть несколько имён,
и все они показываются. Значения по режимам (светлая и тёмная тема) — отдельные строки
одного токена.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone

from . import color as colorm
from . import db as dbm

# Таблица токенов создаётся вместе со всей схемой базы (db.SCHEMA). Здесь — пусто, чтобы
# старые вызовы executescript(tokens.SCHEMA) ничего не ломали.
SCHEMA = ""

_REF = re.compile(r"^\{([^{}]+)\}$")
_NAME_COLS = ("name", "token", "имя", "название", "variable", "переменная")
_VALUE_HINTS = ("value", "hex", "color", "colour", "значение", "цвет")
_SKIP_VALUE = ("тип значений", "type of value", "value type")


class TokensError(ValueError):
    pass


# ---------------------------------------------------------------- разбор

# Вид токена — как его называют форматы, к нескольким понятным группам.
_KINDS = {
    "color": "color", "colour": "color",
    "float": "number", "number": "number", "dimension": "number", "spacing": "number", "sizing": "number",
    "borderradius": "number", "borderwidth": "number", "opacity": "number", "fontsize": "number",
    "lineheight": "number", "letterspacing": "number", "fontweight": "number", "fontweights": "number",
    "string": "string", "fontfamily": "string", "fontfamilies": "string", "text": "string", "content": "string",
    "boolean": "boolean", "typography": "typography", "shadow": "shadow", "boxshadow": "shadow",
}


def _kind(t) -> str:
    return _KINDS.get(str(t or "").replace("_", "").replace("-", "").lower(), str(t or "").lower() or "other")


def _row(name, kind, value, mode="", collection="", scope="", library="", key="") -> dict:
    """Одна строка справочника: токен в одной теме. Цвет разобран в RRGGBB и прозрачность."""
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False) if value is not None else ""
    c = colorm.parse(raw) if kind in ("color", "other", "") or not kind else None
    if c and kind in ("other", ""):
        kind = "color"
    return {"name": str(name).strip(), "type": kind, "mode": str(mode or ""), "value": raw.strip(),
            "color": c[0] if c and kind == "color" else None, "alpha": c[1] if c and kind == "color" else None,
            "collection": str(collection or ""), "scope": str(scope or ""), "library": str(library or ""),
            "key": str(key or "")}


def _plain(kind: str, v):
    """Значение формата DTCG 2025.10 → обычное: цвет-объект {colorSpace, components, alpha, hex}
    → «#RRGGBB[AA]», размер {value, unit} → «16px». Остальное — как есть."""
    if not isinstance(v, dict):
        return v
    if kind == "color" and ("colorSpace" in v or "hex" in v):
        hexv = v.get("hex")
        comps = v.get("components")
        if not hexv and str(v.get("colorSpace", "srgb")).lower() == "srgb" and isinstance(comps, list) and len(comps) == 3 \
                and all(isinstance(x, (int, float)) for x in comps):
            hexv = "#" + "".join("%02X" % max(0, min(255, round(x * 255))) for x in comps)
        if not hexv:
            return v
        a = v.get("alpha")
        return hexv.upper() + ("%02X" % round(a * 255) if isinstance(a, (int, float)) and a < 1 else "")
    if kind == "number" and "value" in v and set(v) <= {"value", "unit"}:
        return f"{v['value']}{v.get('unit') or ''}"
    return v


def _from_tree(data) -> list[dict]:
    """W3C Design Tokens и Tokens Studio: обходит дерево, листья — словари с $value / value."""
    flat: dict[str, object] = {}
    types: dict[str, str] = {}

    def visit(obj, path, inherited_type):
        if not isinstance(obj, dict):
            return
        t = obj.get("$type") or inherited_type
        if "$value" in obj or ("value" in obj and (not isinstance(obj.get("value"), dict) or obj.get("type") or obj.get("$type"))):
            key = ".".join(path)
            flat[key] = obj.get("$value", obj.get("value"))
            types[key] = obj.get("$type") or obj.get("type") or t or ""
            return
        for k, v in obj.items():
            if not k.startswith("$"):
                visit(v, path + [k], t)

    visit(data, [], None)

    def resolve(v, depth=0):
        if depth > 16:
            return None
        m = _REF.match(str(v).strip()) if isinstance(v, str) else None
        if m:
            return resolve(flat.get(m.group(1)), depth + 1)
        return v

    out = []
    for key, raw in flat.items():
        kind = _kind(types.get(key))
        name, coll = key.replace(".", "/"), key.split(".")[0] if "." in key else ""
        val = _plain(kind, resolve(raw))
        # Значения по режимам — словарь «режим → значение» у цвета (у типографики и теней
        # словарь — это само значение).
        if isinstance(val, dict) and kind not in ("typography", "shadow"):
            for mode, mv in val.items():
                out.append(_row(name, kind, _plain(kind, resolve(mv)), mode, coll))
            continue
        out.append(_row(name, kind, val, "", coll))
    return out


def _from_list(items) -> list[dict]:
    """Выгрузка переменных: [{name, value | values | valuesByMode, type?, collection?, scopes?}]."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        kind = _kind(it.get("type") or it.get("resolvedType"))
        coll = str(it.get("collection") or "")
        scope = ",".join(it.get("scopes") or []) if isinstance(it.get("scopes"), list) else str(it.get("scope") or "")
        key = str(it.get("key") or "")
        vals = it.get("values") or it.get("valuesByMode")
        if isinstance(vals, dict):
            for mode, v in vals.items():
                out.append(_row(name, kind, v, mode, coll, scope, "", key))
        elif isinstance(vals, list):
            for i, v in enumerate(vals):
                out.append(_row(name, kind, v, str(i + 1), coll, scope, "", key))
        else:
            out.append(_row(name, kind, it.get("value"), "", coll, scope, "", key))
    return out


def _from_csv(text: str) -> list[dict]:
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return []
    labels = [h.strip() for h in rows[0]]
    head = [h.lower() for h in labels]
    name_i = next((i for i, h in enumerate(head) if h in _NAME_COLS), None)
    if name_i is None:
        raise TokensError("The CSV has no token name column (name, token or Имя)")
    value_is = [i for i, h in enumerate(head)
                if i != name_i and any(x in h for x in _VALUE_HINTS) and h not in _SKIP_VALUE]
    col = lambda *names: next((i for i, h in enumerate(head) if h in names), None)
    type_i, coll_i = col("тип", "type"), col("коллекция", "collection")
    scope_i, lib_i = col("скоуп", "scope", "scopes"), col("библиотека", "library")
    key_i = col("ключ", "key", "variable key")
    get = lambda r, i: r[i].strip() if i is not None and i < len(r) else ""
    out = []
    for r in rows[1:]:
        name = get(r, name_i)
        if not name:
            continue
        kind = _kind(get(r, type_i)) if get(r, type_i) else ""
        coll, scope, lib, key = get(r, coll_i), get(r, scope_i), get(r, lib_i), get(r, key_i)
        values = [(labels[i] if len(value_is) > 1 else "", get(r, i)) for i in value_is]
        filled = [(m, v) for m, v in values if v]
        if not filled:
            # Значения в файле нет (так бывает у чисел и строк в выгрузках) — токен всё равно
            # есть в системе, показываем его с пометкой.
            out.append(_row(name, kind or "other", "", "", coll, scope, lib, key))
            continue
        for m, v in filled:
            # Несколько колонок значений — это темы (режимы переменной): имя темы — заголовок
            # колонки, как его назвал человек.
            out.append(_row(name, kind, v, m, coll, scope, lib, key))
    return out


def parse_all(text: str, filename: str = "") -> list[dict]:
    """Текст справочника → все токены: цвета, числа, строки, типографика, тени — по темам."""
    s = (text or "").strip()
    if not s:
        raise TokensError("The file is empty")
    if s[:1] in "{[":
        try:
            data = json.loads(s)
        except ValueError as e:
            raise TokensError("The file looks like JSON but cannot be read") from e
        if isinstance(data, list):
            rows = _from_list(data)
        elif isinstance(data, dict) and isinstance(data.get("variables"), list):
            rows = _from_list(data["variables"])
        else:
            rows = _from_tree(data)
    else:
        rows = _from_csv(s)
    # Повтор одной и той же строки — одна строка. Разные имена с одним значением остаются.
    seen, uniq = set(), []
    for row in rows:
        key = tuple(row.values())
        if key not in seen:
            seen.add(key)
            uniq.append(row)
    if not uniq:
        raise TokensError("No tokens found in the file")
    return uniq


def parse(text: str, filename: str = "") -> list[tuple]:
    """Только цветовые токены: [(имя, RRGGBB, прозрачность, режим, коллекция)]."""
    rows = [(r["name"], r["color"], r["alpha"], r["mode"], r["collection"]) for r in parse_all(text, filename) if r["color"]]
    seen, uniq = set(), []
    for row in rows:
        if row not in seen:
            seen.add(row)
            uniq.append(row)
    if not uniq:
        raise TokensError("No color tokens found in the file")
    return uniq


def store(con, rows: list, filename: str, project: int | None = None) -> int:
    """Справочник проекта целиком заменяется новым файлом. rows — строки parse_all или цветовые
    кортежи parse."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    full = [r if isinstance(r, dict) else {"name": r[0], "type": "color", "mode": r[3], "value": "#" + r[1],
                                            "color": r[1], "alpha": r[2], "collection": r[4], "scope": "", "library": "", "key": ""}
            for r in rows]
    with dbm.writing(con):
        con.execute("DELETE FROM tokens WHERE project_id IS ?", (project,))
        con.executemany("INSERT INTO tokens (name, color, alpha, mode, collection, project_id, type, value, scope, library, key)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(r["name"], r["color"], r["alpha"], r["mode"], r["collection"], project, r["type"], r["value"],
                          r["scope"], r["library"], r.get("key") or "") for r in full])
        if project is not None:
            con.execute("UPDATE projects SET tokens_file = ?, tokens_loaded_at = ? WHERE id = ?", (filename, now, project))
        else:
            for k, v in (("tokens_file", filename), ("tokens_loaded_at", now)):
                con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, v))
    return len(full)


class Index:
    """Справочник в памяти: поиск по точному значению и ближайшего по виду."""

    def __init__(self, rows: list[tuple], source: str = "library", theme: str | None = None, all_rows=None):
        # source: «library» — загруженный справочник; «files» — выведен из стилей и переменных
        # самих макетов, когда справочника нет. theme — тема, с которой сверяем (None — все);
        # all_rows — справочник целиком, со всеми темами, для показа переменных.
        self.source = source
        self.theme = theme
        self.all_rows = all_rows if all_rows is not None else rows
        self.by_value: dict[tuple[str, int], list[str]] = {}
        self.items: list[tuple[str, str, int, tuple]] = []
        for name, c, a, _mode, _coll in rows:
            names = self.by_value.setdefault((c, a), [])
            if name not in names:
                names.append(name)
            self.items.append((name, c, a, colorm.lab(c)))
        self.names = sorted({r[0] for r in rows})
        # Статус цвета зависит только от цвета и справочника — запоминаем: на тысячах цветов
        # сравнение с каждым токеном по CIEDE2000 занимает секунды.
        self.classified: dict[tuple[str, int], dict] = {}
        self.sig = hash((source, theme, tuple(rows)))   # подпись справочника — для памяти результатов

    def __bool__(self) -> bool:
        return bool(self.items)

    def exact(self, c: str, a: int) -> list[str]:
        return self.by_value.get((c, a), [])

    def nearest(self, c: str, a: int) -> tuple[str, str, int, float, int] | None:
        """Ближайший токен: (имя, RRGGBB, прозрачность, разница цвета, разница прозрачности).

        Разница прозрачности отдаётся отдельно: у чёрного 15% и чёрного 100% разница цвета
        нулевая, и без второго числа «разница 0» читалась бы как «это тот же токен»."""
        if not self.items:
            return None
        lab = colorm.lab(c)
        best = None
        for name, tc, ta, tlab in self.items:
            d = colorm.de2000(lab, tlab)
            # Разница в прозрачности весит как заметная разница цвета.
            score = d + abs(ta - a) / 4
            if best is None or score < best[0]:
                best = (score, name, tc, ta, d)
        return best[1], best[2], best[3], round(best[4], 2), abs(best[3] - a)


def _same_colour(self, c: str):
    """Токен того же цвета без учёта прозрачности (глазом не отличить): (имя, RRGGBB, прозрачность, разница)."""
    lab = colorm.lab(c)
    best = None
    for name, tc, ta, tlab in self.items:
        d = colorm.de2000(lab, tlab)
        if d < 1.0 and (best is None or d < best[3]):
            best = (name, tc, ta, d)
    return best


Index.same_colour = _same_colour


_LOADED: dict[tuple, Index] = {}


def themes_of(rows) -> list[str]:
    """Темы справочника по порядку появления. Пустой режим — не тема."""
    seen = []
    for r in rows:
        if r[3] and r[3] not in seen:
            seen.append(r[3])
    return seen


def for_theme(rows, theme: str | None) -> list[tuple]:
    """Значения, действующие в теме. У переменной со значением в этой теме — оно; у постоянной
    (одно значение на все темы) — её значение; у переменной без значения в этой теме — ничего."""
    if not theme:
        return list(rows)
    by_name: dict[str, list] = {}
    for r in rows:
        by_name.setdefault(r[0], []).append(r)
    out = []
    for name, rs in by_name.items():
        own = [r for r in rs if r[3] == theme]
        if own:
            out += own
        elif len({(r[1], r[2]) for r in rs}) == 1:
            out.append(rs[0])
    return out


def load(con, project: int | None = None, theme: str | None = None) -> Index:
    """Справочник проекта. Пока он не менялся, отдаётся тот же объект — с запомненными статусами.

    Если справочник проекту не загружен, система выводится из самих макетов: цвета, которые
    где-то в файлах проекта привязаны к стилю или переменной (см. from_files)."""
    rows = con.execute("SELECT name, color, alpha, mode, collection FROM tokens WHERE project_id IS ? AND color IS NOT NULL"
                       " ORDER BY 1, 2, 3, 4, 5", (project,)).fetchall()
    source = "library"
    if not rows and project is not None:
        from . import memo
        rows = memo.cached(con, "tokens-from-files", [project], lambda: from_files(con, project))
        source = "files"
    if theme and theme not in themes_of(rows):
        theme = None
    key = (project, source, theme, tuple(rows))
    got = _LOADED.get(key)
    if got is None:
        if len(_LOADED) > 16:
            _LOADED.clear()
        got = _LOADED[key] = Index(for_theme(rows, theme), source, theme, rows)
    return got


def from_files(con, project: int) -> list[tuple]:
    """Система цветов из макетов: каждый сплошной цвет, который хоть где-то в файлах проекта
    задан через стиль или переменную. Имя — имя стиля; у переменной — «Variable», потому что
    имена переменных Figma через API отдаёт только на тарифе Enterprise."""
    rows = con.execute(
        "SELECT p.src, p.color, p.alpha, COUNT(*) FROM paints p"
        " WHERE p.kind = 'solid' AND p.src IS NOT NULL"
        " AND p.file_key IN (SELECT file_key FROM sources WHERE project_id = ?)"
        " GROUP BY p.src, p.color, p.alpha", (project,)).fetchall()
    out = set()
    for src, c, a, _n in rows:
        # Имя переменной неизвестно — каждое её значение отдельной строкой, иначе все переменные
        # сложились бы в одну с десятками значений.
        name = src[2:] if src.startswith("s:") else f"Variable · #{c}" + (f" {a}%" if a < 100 else "")
        out.add((name, c, a, None, "Styles in the files" if src.startswith("s:") else "Variables in the files"))
    return sorted(out)


def usage(idx: Index, colours: list[dict]) -> list[dict]:
    """Токены справочника против макетов: сколько раз значение токена встречается и сколько из
    этого набрано вручную. Токены, которых в макетах нет совсем, — кандидаты на удаление
    или признак, что макеты живут своей жизнью.

    Какой именно переменной привязан цвет, Figma отдаёт только на тарифе Enterprise, поэтому
    счёт — по значению: все применения цвета, равного значению токена."""
    by_value = {(c["color"], c["alpha"]): c for c in colours}
    owners: dict[tuple, set] = {}
    for name, c, a, _m, _coll in idx.all_rows:
        owners.setdefault((c, a), set()).add(name)
    tokens: dict[str, dict] = {}
    for name, c, a, mode, coll in idx.all_rows:
        t = tokens.setdefault(name, {"name": name, "collection": coll or "", "values": []})
        if any(v["color"] == c and v["alpha"] == a and v["mode"] == mode for v in t["values"]):
            continue
        used = by_value.get((c, a)) or {}
        t["values"].append({"mode": mode or "", "color": c, "alpha": a, "uses": used.get("uses", 0),
                            "raw": used.get("raw", 0), "files": used.get("files", 0), "screens": used.get("screens", 0),
                            "shared": len(owners.get((c, a), ())) > 1})
    order = {m: i for i, m in enumerate(themes_of(idx.all_rows))}
    out = []
    for t in tokens.values():
        t["values"].sort(key=lambda v: order.get(v["mode"], -1))
        distinct = {(v["color"], v["alpha"]) for v in t["values"]}
        t["constant"] = len(distinct) == 1
        if t["constant"]:
            t["values"] = t["values"][:1]
        # Применения переменной — по разным значениям, без двойного счёта одинаковых.
        seen = {}
        for v in t["values"]:
            seen[(v["color"], v["alpha"])] = v
        t["uses"] = sum(v["uses"] for v in seen.values())
        t["raw"] = sum(v["raw"] for v in seen.values())
        t["screens"] = max((v["screens"] for v in seen.values()), default=0)
        t["files"] = max((v["files"] for v in seen.values()), default=0)
        out.append(t)
    out.sort(key=lambda t: (-t["uses"], t["name"]))
    return out


# ---------------------------------------------------------------- страница токенов

# Область применения числового токена → какие числа макетов с ним сверять.
_SCOPE_KINDS = {"STROKE_FLOAT": ("stroke",), "GAP": ("gap",), "CORNER_RADIUS": ("radius",),
                "ALL_SCOPES": ("gap", "padding", "radius", "stroke"), "": ("gap", "padding", "radius", "stroke")}
_PX = re.compile(r"(\d+(?:[.,]\d+)?)\s*px\b", re.I)


def _number_kinds(name: str, scope: str) -> tuple:
    for s in (scope or "").split(","):
        if s.strip() in _SCOPE_KINDS and s.strip() not in ("ALL_SCOPES", ""):
            return _SCOPE_KINDS[s.strip()]
    low = name.lower()
    for hint, kinds in (("radius", ("radius",)), ("border", ("stroke",)), ("stroke", ("stroke",)),
                        ("gap", ("gap",)), ("padding", ("padding",)), ("spacing", ("gap", "padding")), ("space", ("gap", "padding"))):
        if hint in low:
            return kinds
    if "opacity" in low or "OPACITY" in (scope or "") or "%" in name:
        return ()
    return _SCOPE_KINDS[""]


def var_key(var: str) -> tuple[str | None, str]:
    """«VariableID:<ключ>/<id>» → (ключ, id); у своей переменной файла ключа нет: (None, id)."""
    rest = var.split(":", 1)[1] if ":" in var else var
    if "/" in rest:
        k, local = rest.split("/", 1)
        return k, local
    return None, rest


def _mode_of(sig: str | None) -> tuple[str | None, str | None]:
    """«коллекция=режим;…» → (коллекция, режим) для единственной коллекции; иначе первой."""
    if not sig:
        return None, None
    c, _, m = sig.split(";")[0].partition("=")
    return c, m


def _mode_order(m: str):
    try:
        return tuple(int(x) for x in m.split(":"))
    except ValueError:
        return (10 ** 9,)


def catalog(con, project, idx: "Index", colours: list[dict], props: dict, binds: list | None = None,
            styles: dict | None = None) -> dict:
    """Все токены проекта одной страницей: по переменной — вид, коллекция, область, значения
    по темам и сколько раз она встречается в макетах.

    props: {(вид числа, значение): применений} — для сверки числовых токенов.
    binds: [(переменная, темы, RRGGBB, прозрачность, применений, экранов, файлов)] — какие
    переменные привязаны в макетах на самом деле и в какой теме. Если в справочнике есть ключи
    переменных, привязки сопоставляются с токенами точно, а не по совпадению цвета.
    styles: {имя стиля: [применений, экранов, файлов]} — сколько раз стоит каждый стиль."""
    binds = binds or []
    styles = styles or {}
    if idx.source == "files":
        rows = [{"name": n, "type": "color", "mode": m or "", "value": "#" + c, "color": c, "alpha": a,
                 "collection": coll or "", "scope": "", "library": "", "key": ""}
                for n, c, a, m, coll in idx.all_rows if not n.startswith("Variable · ")]
    else:
        rows = [dict(zip(("name", "type", "mode", "value", "color", "alpha", "collection", "scope", "library", "key"), r))
                for r in con.execute("SELECT name, IFNULL(type, 'color'), IFNULL(mode, ''), IFNULL(value, ''), color, alpha,"
                                     " IFNULL(collection, ''), IFNULL(scope, ''), IFNULL(library, ''), IFNULL(key, '')"
                                     " FROM tokens WHERE project_id IS ? ORDER BY rowid", (project,))]
    themes = themes_of([(r["name"], r["color"], r["alpha"], r["mode"], r["collection"]) for r in rows])
    order = {m: i for i, m in enumerate(themes)}
    by_value = {(c["color"], c["alpha"]): c for c in colours}

    # Привязки по переменной: ключ библиотечной или id своей; значения — по теме, в которой
    # переменная показана. Экран без явно включённой темы показывает тему по умолчанию ("").
    bound: dict[str, dict] = {}
    for var, sig, c, a, uses, screens, files in binds:
        k, local = var_key(var)
        b = bound.setdefault(k or local, {"key": k, "local": local, "uses": 0, "screens": 0, "files": 0, "values": {}})
        b["uses"] += uses
        b["screens"] = max(b["screens"], screens)
        b["files"] = max(b["files"], files)
        mode = _mode_of(sig)[1] or ""
        cell = b["values"].setdefault(mode, {})
        cell[(c, a)] = cell.get((c, a), 0) + uses
    top = lambda cell: max(cell.items(), key=lambda kv: kv[1])[0]
    # Явно включённая тема, где все переменные выглядят как по умолчанию, — это она же.
    explicit = {m for b in bound.values() for m in b["values"] if m}
    for m in sorted(explicit, key=_mode_order):
        pairs = [(top(b["values"][""]), top(b["values"][m])) for b in bound.values() if "" in b["values"] and m in b["values"]]
        if pairs and all(x == y for x, y in pairs):
            for b in bound.values():
                if m in b["values"]:
                    cell = b["values"].setdefault("", {})
                    for v, n in b["values"].pop(m).items():
                        cell[v] = cell.get(v, 0) + n
    # Имена тем без справочника неизвестны — «Mode 1» (по умолчанию), «Mode 2»… по порядку режимов.
    used = {m for b in bound.values() for m in b["values"]}
    all_modes = ([""] if "" in used else []) + sorted(used - {""}, key=_mode_order)
    mode_label = {m: f"Mode {i + 1}" for i, m in enumerate(all_modes)} if len(all_modes) > 1 else {}
    lib_keys = {r["key"] for r in rows if r["key"]}
    exact = bool(lib_keys) or idx.source == "files"

    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (r["name"], r["type"], r["collection"], r["library"])
        g = groups.setdefault(key, {"name": r["name"], "type": r["type"], "collection": r["collection"],
                                    "library": r["library"], "scope": r["scope"], "values": [], "keys": set()})
        if r["key"]:
            g["keys"].add(r["key"])
        if r["scope"] and r["scope"] not in g["scope"]:
            g["scope"] = ",".join(x for x in (g["scope"], r["scope"]) if x)
        if not r["value"] and not r["color"]:
            continue
        v = {"mode": r["mode"], "value": r["value"], "color": r["color"], "alpha": r["alpha"],
             "uses": 0, "raw": 0, "screens": 0, "files": 0, "from_name": False}
        if r["color"]:
            used = by_value.get((r["color"], r["alpha"])) or {}
            v.update(uses=used.get("uses", 0), raw=used.get("raw", 0), screens=used.get("screens", 0), files=used.get("files", 0))
        if not any(x["mode"] == v["mode"] and x["value"] == v["value"] for x in g["values"]):
            g["values"].append(v)

    # Переменные, привязанные в макетах, которых нет в справочнике (или справочника нет вовсе):
    # имени Figma не отдаёт, но значения одной переменной собираются вместе.
    for b in bound.values():
        if b["key"] and b["key"] in lib_keys:
            continue
        coll = "Variables in the files" if idx.source == "files" else "Bound in the files, not in the library"
        short = (b["key"] or b["local"])[:10]
        values = []
        for mode, cells in b["values"].items():
            c, a = top(cells)                                         # в одной теме значение одно
            values.append({"mode": mode_label.get(mode, ""), "value": "#" + c, "color": c, "alpha": a,
                           "uses": sum(cells.values()), "raw": 0, "screens": 0, "files": 0, "from_name": False})
        g = {"name": f"Variable {short}", "type": "color", "collection": coll, "library": "", "scope": "",
             "keys": {b["key"] or b["local"]}, "unknown": True, "values": values}
        groups[("~var", short, coll, "")] = g
    for label in mode_label.values():
        if label not in themes:
            themes.append(label)
            order[label] = len(order)

    out = []
    for g in groups.values():
        g["values"].sort(key=lambda v: order.get(v["mode"], -1))
        if g["type"] == "number":
            if not g["values"]:
                m = _PX.search(g["name"])
                if m:
                    g["values"].append({"mode": "", "value": m.group(1).replace(",", "."), "color": None, "alpha": None,
                                        "uses": 0, "raw": 0, "screens": 0, "files": 0, "from_name": True})
            g["kinds"] = list(_number_kinds(g["name"], g["scope"]))
            for v in g["values"]:
                try:
                    n = round(float(str(v["value"]).replace("px", "").replace(",", ".")), 2)
                except ValueError:
                    continue
                v["uses"] = sum(props.get((k, n), 0) for k in g["kinds"])
        distinct = {(v["value"], v["color"], v["alpha"]) for v in g["values"]}
        g["constant"] = len(distinct) <= 1
        if g["constant"]:
            g["values"] = g["values"][:1]
        g["uses"] = sum(v["uses"] for v in {(v["value"], v["color"]): v for v in g["values"]}.values())
        g["raw"] = sum(v["raw"] for v in g["values"])
        g["screens"] = max((v["screens"] for v in g["values"]), default=0)
        g["files"] = max((v["files"] for v in g["values"]), default=0)
        # Точные привязки: сколько раз именно эта переменная стоит в макетах.
        bs = [bound[k] for k in g.pop("keys") if k in bound]
        g["bound"] = sum(b["uses"] for b in bs) if (exact or bs) else None
        if idx.source == "files" and not g.get("unknown") and g["name"] in styles:
            # Стиль цвета: его привязка — сам стиль, а не переменная.
            g["bound"], g["screens"], g["files"] = styles[g["name"]]
        if bs:
            g["screens"] = max(g["screens"], max(b["screens"] for b in bs))
            g["files"] = max(g["files"], max(b["files"] for b in bs))
        g["empty"] = not g["values"]
        out.append(g)
    rank = {"color": 0, "number": 1, "string": 2, "typography": 3, "shadow": 4}
    out.sort(key=lambda g: (rank.get(g["type"], 9), -g["uses"], g["name"]))
    return {"themes": themes, "items": out, "library": idx.source, "theme": idx.theme, "exact": exact,
            "keys": len(lib_keys), "bound_total": sum(b["uses"] for b in bound.values()),
            "bound_unknown": sum(1 for b in bound.values() if not (b["key"] and b["key"] in lib_keys))}
