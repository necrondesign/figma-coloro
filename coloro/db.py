"""Локальная база: один файл SQLite.

Данные лежат по (файл, страница), а не по ссылке, поэтому одна и та же страница, пришедшая
через две разные ссылки, хранится один раз — двойной счёт невозможен по устройству.

Загрузка ничего не отбрасывает: скрытые слои, архивные страницы, служебные секции — всё
ложится с метками. Что учитывать, решают фильтры при просмотре.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .textnorm import norm

# Формат данных. Поднимается, когда меняется то, что извлекается из макета:
# файлы, загруженные в старом формате, при следующем обновлении перезагружаются.
FORMAT = 5

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

-- pages — все страницы файла при последней проверке ([[id, название], …]): по ним видно,
-- нужно ли что-то докачать, без тяжёлого запроса к Figma.
CREATE TABLE IF NOT EXISTS files (
    file_key TEXT PRIMARY KEY, name TEXT, version TEXT, last_modified TEXT,
    checked_at TEXT, loaded_at TEXT, format INTEGER, pages TEXT
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
--   ovr   — у инстанса есть переопределения относительно мастер-компонента
--   tnorm, nnorm — текст и название в нижнем регистре, «ё» как «е»: по ним идёт поиск
CREATE TABLE IF NOT EXISTS nodes (
    file_key TEXT, page_id TEXT, id TEXT, parent_id TEXT, type TEXT, name TEXT,
    hid INTEGER, sect INTEGER, pinst TEXT, comp TEXT, text TEXT,
    x INTEGER, y INTEGER, w INTEGER, h INTEGER,
    font INTEGER, tstyle INTEGER, first_seen TEXT, screen TEXT, anchor TEXT,
    ovr INTEGER, tnorm TEXT, nnorm TEXT,
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
-- У краски — копия полей слоя, по которым фильтруют: скрыт ли, внутри ли компонента, секция,
-- экран, когда появился. Цвета считаются по одной этой таблице, не трогая слои.
CREATE TABLE IF NOT EXISTS paints (
    file_key TEXT, page_id TEXT, node_id TEXT, slot TEXT, kind TEXT,
    color TEXT, alpha INTEGER, src TEXT, grad INTEGER,
    hid INTEGER, inst INTEGER, sect INTEGER, screen TEXT, first_seen TEXT
);
CREATE INDEX IF NOT EXISTS paints_page ON paints (file_key, page_id);
CREATE INDEX IF NOT EXISTS paints_color ON paints (color);

-- Компоненты, на которые ссылаются инстансы файла: имя, набор вариантов, библиотека или свой.
--   remote — 1: из библиотеки, 0: заведён в этом файле
CREATE TABLE IF NOT EXISTS components (
    file_key TEXT, id TEXT, key TEXT, name TEXT, set_id TEXT, set_name TEXT, remote INTEGER,
    PRIMARY KEY (file_key, id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS nodes_comp ON nodes (file_key, comp);

-- Числа со шкалой: kind — gap | padding | radius | stroke; bound — привязано к переменной.
CREATE TABLE IF NOT EXISTS props (
    file_key TEXT, page_id TEXT, node_id TEXT, kind TEXT, value REAL, bound INTEGER
);
CREATE INDEX IF NOT EXISTS props_page ON props (file_key, page_id);

-- Тени и размытия: type — DROP_SHADOW | INNER_SHADOW | LAYER_BLUR | BACKGROUND_BLUR.
CREATE TABLE IF NOT EXISTS effects (
    file_key TEXT, page_id TEXT, node_id TEXT, type TEXT, color TEXT, alpha INTEGER,
    x REAL, y REAL, radius REAL, spread REAL, src TEXT
);
CREATE INDEX IF NOT EXISTS effects_page ON effects (file_key, page_id);

-- Картинки в заливках: ref — одна и та же картинка в разных местах.
CREATE TABLE IF NOT EXISTS images (
    file_key TEXT, page_id TEXT, node_id TEXT, ref TEXT, mode TEXT
);
CREATE INDEX IF NOT EXISTS images_page ON images (file_key, page_id);

-- Справочник токенов цвета: загружается из файла дизайн-системы.
CREATE TABLE IF NOT EXISTS tokens (
    name TEXT, color TEXT, alpha INTEGER, mode TEXT, collection TEXT
);
CREATE INDEX IF NOT EXISTS tokens_value ON tokens (color, alpha);

-- Итоговые числа после каждого обновления: из них стрелки «стало лучше или хуже».
CREATE TABLE IF NOT EXISTS snapshots (
    taken_at TEXT, file_key TEXT, metrics TEXT,
    PRIMARY KEY (taken_at, file_key)
) WITHOUT ROWID;
"""

# Колонки, добавленные после первого формата: в старой базе их дописываем, а сами данные
# обновятся при следующей загрузке — формат поднят, и файлы перезагрузятся.
_ADDED = {"nodes": (("screen", "TEXT"), ("anchor", "TEXT"), ("ovr", "INTEGER"), ("tnorm", "TEXT"), ("nnorm", "TEXT")),
          "files": (("pages", "TEXT"),),
          "paints": (("hid", "INTEGER"), ("inst", "INTEGER"), ("sect", "INTEGER"), ("screen", "TEXT"),
                     ("first_seen", "TEXT"))}
# Индексы, которые больше не нужны: в старой базе их убираем, чтобы не занимали место.
_DROPPED = ("paints_node", "props_node", "effects_node", "images_node")


# Схема создаётся один раз на путь: несколько потоков, открывших новую базу одновременно,
# иначе спорят за блокировку на CREATE TABLE.
_SCHEMA_LOCK = threading.Lock()
_READY: set[str] = set()

# Запись в базу из параллельных загрузок — по очереди. SQLite и так пускает одного писателя,
# но ждёт его ограниченное время: большая страница пишется дольше, и следующий поток падал
# бы с «database is locked». Очередь в самой программе ждёт сколько нужно. Чтение не ждёт.
WRITE_LOCK = threading.RLock()


class writing:
    """with dbm.writing(con): … — транзакция записи в порядке очереди."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        WRITE_LOCK.acquire()
        try:
            return self.con.__enter__()
        except BaseException:
            WRITE_LOCK.release()
            raise

    def __exit__(self, *exc):
        try:
            return self.con.__exit__(*exc)
        finally:
            WRITE_LOCK.release()


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=60, check_same_thread=False)
    # WAL: просмотр не ждёт, пока идёт запись. Режим хранится в самом файле базы, а его
    # включение требует исключительного доступа — поэтому только если он ещё не включён:
    # иначе новое соединение падает, пока другой поток пишет большую страницу.
    if con.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
        con.execute("PRAGMA journal_mode=WAL")
    # NORMAL — штатная пара к WAL: при сбое питания теряется только последняя транзакция,
    # но не целостность.
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=-64000")
    # Встроенная lower() в SQLite не опускает регистр кириллицы: «Кнопка» и «кнопка» для неё
    # разные строки. Своя функция — та же, что строит поисковые колонки при загрузке.
    con.create_function("norm", 1, norm, deterministic=True)
    with _SCHEMA_LOCK:
        if str(p.resolve()) not in _READY:
            con.executescript(SCHEMA)
            for table, cols in _ADDED.items():
                have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                for col, kind in cols:
                    if col not in have:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
            for index in _DROPPED:
                con.execute(f"DROP INDEX IF EXISTS {index}")
            con.commit()
            _READY.add(str(p.resolve()))
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return con


def path_of(con: sqlite3.Connection) -> str:
    """Файл, на который открыто соединение, — чтобы открыть рядом ещё одно."""
    return con.execute("PRAGMA database_list").fetchone()[2]


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
        # Отдельная короткая запись сразу с фиксацией: словарь пополняется во время скачивания
        # страницы, и открытая транзакция держала бы базу минутами — параллельные загрузки
        # других файлов упирались бы в «database is locked».
        with writing(self.con):
            self.con.execute("INSERT OR IGNORE INTO vals (v) VALUES (?)", (value,))
            got = self.con.execute("SELECT id FROM vals WHERE v = ?", (value,)).fetchone()[0]
        self.cache[value] = got
        return got
