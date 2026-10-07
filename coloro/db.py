"""Локальная база: один файл SQLite.

Данные лежат по (файл, страница), а не по ссылке, поэтому одна и та же страница, пришедшая
через две разные ссылки, хранится один раз — двойной счёт невозможен по устройству.

Загрузка ничего не отбрасывает: скрытые слои, архивные страницы, служебные секции — всё
ложится с метками. Что учитывать, решают фильтры при просмотре.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Формат данных. Поднимается, когда меняется то, что извлекается из макета:
# файлы, загруженные в старом формате, при следующем обновлении перезагружаются.
FORMAT = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID;

-- Повторяющиеся строки (шрифты, названия стилей, пути секций, рецепты градиентов)
-- хранятся один раз, а в таблицах — номером.
CREATE TABLE IF NOT EXISTS vals (id INTEGER PRIMARY KEY, v TEXT UNIQUE);

-- То, что человек добавил: ссылка и, при желании, какие страницы брать (JSON-список
-- образцов названий; NULL — все страницы).
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY, url TEXT UNIQUE, file_key TEXT, node_id TEXT,
    pages TEXT, added_at TEXT
);

CREATE TABLE IF NOT EXISTS files (
    file_key TEXT PRIMARY KEY, name TEXT, version TEXT, last_modified TEXT,
    checked_at TEXT, loaded_at TEXT, format INTEGER
) WITHOUT ROWID;

-- status: ok — загружена целиком; failed — не загрузилась, в error причина.
-- version — версия файла, с которой страница загружена.
CREATE TABLE IF NOT EXISTS pages (
    file_key TEXT, page_id TEXT, name TEXT, archived INTEGER, position INTEGER,
    version TEXT, loaded_at TEXT, status TEXT, error TEXT, nodes INTEGER,
    PRIMARY KEY (file_key, page_id)
) WITHOUT ROWID;

-- Все слои, включая безымянные фигуры: цвета считаются по всем, а отсеять фигуры
-- с названием по умолчанию — дело фильтра поиска.
--   hid   — скрыт сам или кто-то из родителей
--   sect  — путь секций над слоем («Для арта / Иконки»), номер в vals
--   pinst — ближайший родитель-инстанс
--   x, y, w, h — рамка на холсте в десятых долях пикселя
--   first_seen — когда слой впервые появился в базе (переживает перезагрузку)
--   screen — экран, в который входит слой: самый внешний кадр под страницей
--   anchor — ближайший слой, на который открывается ссылка Figma (у слоёв внутри
--            инстанса id составной, и ссылка на них не работает — ведём на инстанс)
CREATE TABLE IF NOT EXISTS nodes (
    file_key TEXT, page_id TEXT, id TEXT, parent_id TEXT, type TEXT, name TEXT,
    hid INTEGER, sect INTEGER, pinst TEXT, comp TEXT, text TEXT,
    x INTEGER, y INTEGER, w INTEGER, h INTEGER,
    font INTEGER, tstyle INTEGER, first_seen TEXT, screen TEXT, anchor TEXT,
    PRIMARY KEY (file_key, id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS nodes_page ON nodes (file_key, page_id);

-- Каждое применение цвета: сплошная заливка или обводка — одна строка, градиент —
-- строка на каждый стоп.
--   slot  — fill | stroke
--   kind  — solid | stop
--   color — RRGGBB
--   alpha — непрозрачность в процентах. У сплошной краски — прозрачность цвета, умноженная
--           на прозрачность краски (это и есть значение пипетки). У стопа — только его своя.
--   src   — NULL: задан вручную; «v»: переменная; «s:Название»: стиль
--   grad  — рецепт градиента (номер в vals) — только у стопов
CREATE TABLE IF NOT EXISTS paints (
    file_key TEXT, page_id TEXT, node_id TEXT, slot TEXT, kind TEXT,
    color TEXT, alpha INTEGER, src TEXT, grad INTEGER
);
CREATE INDEX IF NOT EXISTS paints_page ON paints (file_key, page_id);
-- Краска по слою: без него каждый запрос с фильтром по слоям перебирал бы все краски файла
-- на каждый слой — на 259 тысячах слоёв это минуты вместо долей секунды.
CREATE INDEX IF NOT EXISTS paints_node ON paints (file_key, node_id);
CREATE INDEX IF NOT EXISTS paints_color ON paints (color);

-- Итоговые числа после каждого обновления: из них стрелки «стало лучше или хуже».
CREATE TABLE IF NOT EXISTS snapshots (
    taken_at TEXT, file_key TEXT, metrics TEXT,
    PRIMARY KEY (taken_at, file_key)
) WITHOUT ROWID;
"""

# Колонки, добавленные после первого формата: в старой базе их дописываем, а сами данные
# обновятся при следующей загрузке — формат поднят, и файлы перезагрузятся.
_ADDED = {"nodes": (("screen", "TEXT"), ("anchor", "TEXT"))}


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=30, check_same_thread=False)
    # WAL: просмотр не ждёт, пока идёт запись. NORMAL — штатная пара к WAL:
    # при сбое питания теряется только последняя транзакция, но не целостность.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=-64000")
    con.executescript(SCHEMA)
    for table, cols in _ADDED.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, kind in cols:
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return con


class Interner:
    """Словарь повторяющихся строк: строка → номер, с запоминанием на время загрузки."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.cache: dict[str, int] = {}

    def __call__(self, value: str | None) -> int | None:
        if value is None or value == "":
            return None
        got = self.cache.get(value)
        if got is not None:
            return got
        self.con.execute("INSERT OR IGNORE INTO vals (v) VALUES (?)", (value,))
        got = self.con.execute("SELECT id FROM vals WHERE v = ?", (value,)).fetchone()[0]
        self.cache[value] = got
        return got
