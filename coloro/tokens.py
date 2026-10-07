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

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    name TEXT, color TEXT, alpha INTEGER, mode TEXT, collection TEXT
);
CREATE INDEX IF NOT EXISTS tokens_value ON tokens (color, alpha);
"""

_REF = re.compile(r"^\{([^{}]+)\}$")
_NAME_COLS = ("name", "token", "имя", "название", "variable", "переменная")
_VALUE_HINTS = ("value", "hex", "color", "colour", "значение", "цвет")
_SKIP_VALUE = ("тип значений", "type of value", "value type")


class TokensError(ValueError):
    pass


# ---------------------------------------------------------------- JSON

def _from_tree(data) -> list[tuple]:
    """W3C Design Tokens и Tokens Studio: обходит дерево, листья — словари с $value / value."""
    flat: dict[str, object] = {}
    types: dict[str, str] = {}

    def visit(obj, path, inherited_type):
        if not isinstance(obj, dict):
            return
        t = obj.get("$type") or inherited_type
        if "$value" in obj or ("value" in obj and not isinstance(obj.get("value"), dict)):
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
        if types.get(key) and types[key].lower() not in ("color", "colour"):
            continue
        val = resolve(raw)
        if isinstance(val, dict):            # значения по режимам
            for mode, mv in val.items():
                c = colorm.parse(resolve(mv))
                if c:
                    out.append((key.replace(".", "/"), *c, str(mode), key.split(".")[0]))
            continue
        c = colorm.parse(val)
        if c:
            out.append((key.replace(".", "/"), *c, "", key.split(".")[0] if "." in key else ""))
    return out


def _from_list(items) -> list[tuple]:
    """Выгрузка переменных: [{name, value | values | valuesByMode, collection?}]."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        coll = str(it.get("collection") or "")
        vals = it.get("values") or it.get("valuesByMode")
        if isinstance(vals, dict):
            for mode, v in vals.items():
                c = colorm.parse(v)
                if c:
                    out.append((name, *c, str(mode), coll))
        elif isinstance(vals, list):
            for i, v in enumerate(vals):
                c = colorm.parse(v)
                if c:
                    out.append((name, *c, str(i + 1), coll))
        else:
            c = colorm.parse(it.get("value"))
            if c:
                out.append((name, *c, "", coll))
    return out


# ---------------------------------------------------------------- CSV

def _from_csv(text: str) -> list[tuple]:
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    name_i = next((i for i, h in enumerate(head) if h in _NAME_COLS), None)
    if name_i is None:
        raise TokensError("в CSV не нашлось колонки с именем токена (name, token или «Имя»)")
    value_is = [i for i, h in enumerate(head)
                if i != name_i and any(x in h for x in _VALUE_HINTS) and h not in _SKIP_VALUE]
    type_i = next((i for i, h in enumerate(head) if h in ("тип", "type")), None)
    coll_i = next((i for i, h in enumerate(head) if h in ("коллекция", "collection")), None)
    out = []
    for r in rows[1:]:
        if name_i >= len(r):
            continue
        name = r[name_i].strip()
        if not name:
            continue
        if type_i is not None and type_i < len(r) and r[type_i].strip() and r[type_i].strip().upper() != "COLOR":
            continue
        coll = r[coll_i].strip() if coll_i is not None and coll_i < len(r) else ""
        for n, i in enumerate(value_is):
            if i < len(r):
                c = colorm.parse(r[i])
                if c:
                    out.append((name, *c, str(n + 1) if len(value_is) > 1 else "", coll))
    return out


def parse(text: str, filename: str = "") -> list[tuple]:
    """Текст справочника → [(имя, RRGGBB, прозрачность, режим, коллекция)]."""
    s = (text or "").strip()
    if not s:
        raise TokensError("файл пустой")
    if s[:1] in "{[":
        try:
            data = json.loads(s)
        except ValueError as e:
            raise TokensError("файл похож на JSON, но не разбирается") from e
        if isinstance(data, list):
            rows = _from_list(data)
        elif isinstance(data, dict) and isinstance(data.get("variables"), list):
            rows = _from_list(data["variables"])
        else:
            rows = _from_tree(data)
    else:
        rows = _from_csv(s)
    # Повтор одной и той же строки (один токен, один режим) — одна строка. Разные имена
    # с одним значением остаются разными.
    seen, uniq = set(), []
    for row in rows:
        if row not in seen:
            seen.add(row)
            uniq.append(row)
    if not uniq:
        raise TokensError("цветовых токенов в файле не нашлось")
    return uniq


def store(con, rows: list[tuple], filename: str) -> int:
    con.executescript(SCHEMA)
    with con:
        con.execute("DELETE FROM tokens")
        con.executemany("INSERT INTO tokens VALUES (?, ?, ?, ?, ?)", rows)
        for k, v in (("tokens_file", filename), ("tokens_loaded_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))):
            con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, v))
    return len(rows)


class Index:
    """Справочник в памяти: поиск по точному значению и ближайшего по виду."""

    def __init__(self, rows: list[tuple]):
        self.by_value: dict[tuple[str, int], list[str]] = {}
        self.items: list[tuple[str, str, int, tuple]] = []
        for name, c, a, _mode, _coll in rows:
            names = self.by_value.setdefault((c, a), [])
            if name not in names:
                names.append(name)
            self.items.append((name, c, a, colorm.lab(c)))
        self.names = sorted({r[0] for r in rows})

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


def load(con) -> Index:
    con.executescript(SCHEMA)
    return Index(con.execute("SELECT name, color, alpha, mode, collection FROM tokens").fetchall())
