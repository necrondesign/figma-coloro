"""Память результатов: пока данные не менялись, экран не пересчитывается.

Данные меняются только при обновлении, добавлении или удалении источника и загрузке
справочника. Подпись этих изменений — несколько чисел из маленьких таблиц, она считается за
миллисекунды. Совпала подпись, фильтр и запрос — отдаётся готовый ответ. На миллионах слоёв
это разница между секундами и мгновением при каждом возвращении на экран.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict

_LIMIT = 64
_STORE: OrderedDict = OrderedDict()
_LOCK = threading.Lock()


def stamp(con) -> tuple:
    """Подпись данных: меняется при любой загрузке, удалении и смене справочника."""
    pages = con.execute("SELECT COUNT(*), MAX(loaded_at), TOTAL(nodes), SUM(status = 'ok') FROM pages").fetchone()
    files = con.execute("SELECT COUNT(*), MAX(loaded_at), MAX(checked_at) FROM files").fetchone()
    tokens = con.execute("SELECT COUNT(*), TOTAL(alpha), MAX(name) FROM tokens").fetchone()
    path = con.execute("PRAGMA database_list").fetchone()[2]
    return (path,) + pages + files + tokens


def cached(con, name: str, args, compute):
    """compute() — если такого ответа ещё нет для этих данных и этих аргументов."""
    key = (name, stamp(con), json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))
    with _LOCK:
        if key in _STORE:
            _STORE.move_to_end(key)
            return _STORE[key]
    value = compute()
    with _LOCK:
        _STORE[key] = value
        while len(_STORE) > _LIMIT:
            _STORE.popitem(last=False)
    return value


def clear() -> None:
    with _LOCK:
        _STORE.clear()
