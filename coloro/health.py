"""Общая картина: что хорошо и что плохо, по каждому файлу и в целом.

Для каждого файла считаются одни и те же показатели, и у каждого — уровень: good, fair, bad.
Уровень — это цвет ячейки на карте «файлы × проблемы». Пороги ниже: их легко поменять,
и они одни на весь инструмент.

История: после каждого обновления числа по каждому файлу сохраняются снимком. Из двух
последних снимков получаются стрелки «стало лучше или хуже». Снимок пишется при фильтрах
по умолчанию, поэтому стрелки показываются только при них — сравнивать числа с разными
фильтрами было бы нечестно.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from . import inventory
from .filters import NODE_JOIN, Filter
from .tokens import Index

# Пороги уровней: (до какого значения — хорошо, до какого — так себе). Дальше — плохо.
# Проценты — от 0 до 100.
LEVELS = {
    "raw_pct": (10, 30),          # доля применений цвета, набранных вручную
    "stray": (3, 10),             # левых цветов: почти токен + мимо системы
    "unbound": (1, 5),            # цветов со значением токена, но набранных вручную
    "text_nostyle_pct": (5, 20),  # доля текстов без текстового стиля
    "generic": (5, 20),           # кадров и групп с названием по умолчанию
}

# Метрики, по которым уровень не считается: чем больше, тем не хуже.
INFO = ("uses", "colours", "texts", "layers")

# Названия, которые Figma даёт контейнерам сама.
_GENERIC = ("Frame", "Group", "Section")


def level(metric: str, value) -> str | None:
    lim = LEVELS.get(metric)
    if lim is None or value is None:
        return None
    good, fair = lim
    if value < good:
        return "good"
    if value < fair:
        return "fair"
    return "bad"


def _pct(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def _node_counts(con, filt: Filter) -> dict[str, dict]:
    """Слои, тексты без стиля, безымянные кадры.

    Тексты и названия считаются только у того, что дизайнер положил на экран сам: внутри
    компонента стиль текста и названия слоёв задаёт библиотека, и на экране их не исправить.
    На проверенных макетах это 96% «текстов без стиля» — без этого метрика ругала бы экран
    за библиотеку."""
    where, args = filt.where()
    generic = " OR ".join(f"(n.name = '{g}' OR n.name GLOB '{g} [0-9]*')" for g in _GENERIC)
    out = {}
    for fk, layers, texts, nostyle, gen in con.execute(
            "SELECT n.file_key, COUNT(*), SUM(n.type = 'TEXT' AND n.pinst IS NULL),"
            " SUM(n.type = 'TEXT' AND n.pinst IS NULL AND n.tstyle IS NULL),"
            f" SUM(n.type IN ('FRAME', 'GROUP', 'SECTION') AND n.pinst IS NULL AND ({generic}))"
            " FROM nodes n" + NODE_JOIN + " WHERE " + where + " GROUP BY n.file_key", args):
        out[fk] = {"layers": layers, "texts": texts or 0, "text_nostyle": nostyle or 0, "generic": gen or 0}
    return out


def _colour_counts(con, filt: Filter, idx: Index) -> dict[str, dict]:
    """По каждому файлу: применения, цвета, вручную, левые — одним запросом."""
    where, args = filt.where()
    rows = con.execute(
        "WITH u AS (" + inventory._USES + where + ")"
        " SELECT file_key, color, alpha, COUNT(*), SUM(src IS NULL) FROM u GROUP BY file_key, color, alpha",
        args).fetchall()
    cls: dict[tuple, dict] = {}
    out: dict[str, dict] = {}
    for fk, c, a, uses, raw in rows:
        k = (c, a)
        if k not in cls:
            cls[k] = inventory.classify(c, a, idx)
        st = cls[k]["status"]
        m = out.setdefault(fk, {"uses": 0, "raw": 0, "colours": 0, "near": 0, "alpha": 0, "off": 0, "unbound": 0})
        m["uses"] += uses
        m["raw"] += raw
        m["colours"] += 1
        if st == "near":
            m["near"] += 1
        elif st == "alpha":
            m["alpha"] += 1
        elif st == "off":
            m["off"] += 1
        elif st == "token" and raw:
            m["unbound"] += 1
    return out


def _metrics(colour: dict, nodes: dict, idx: Index) -> dict:
    uses = colour.get("uses", 0)
    m = {
        "layers": nodes.get("layers", 0),
        "uses": uses,
        "colours": colour.get("colours", 0),
        "raw": colour.get("raw", 0),
        "raw_pct": _pct(colour.get("raw", 0), uses),
        "texts": nodes.get("texts", 0),
        "text_nostyle": nodes.get("text_nostyle", 0),
        "text_nostyle_pct": _pct(nodes.get("text_nostyle", 0), nodes.get("texts", 0)),
        "generic": nodes.get("generic", 0),
    }
    # Без справочника токенов «левые» не определить — честнее не показать, чем показать ноль.
    if idx:
        m.update(near=colour.get("near", 0), alpha=colour.get("alpha", 0), off=colour.get("off", 0),
                 stray=colour.get("near", 0) + colour.get("alpha", 0) + colour.get("off", 0),
                 unbound=colour.get("unbound", 0))
    else:
        m.update(near=None, alpha=None, off=None, stray=None, unbound=None)
    m["levels"] = {k: level(k, m.get(k)) for k in LEVELS}
    return m


def overview(con, filt: Filter, idx: Index) -> dict:
    files = {fk: {"file_key": fk, "name": name, "last_modified": lm, "loaded_at": la}
             for fk, name, lm, la in con.execute("SELECT file_key, name, last_modified, loaded_at FROM files")}
    if filt.files:
        files = {k: v for k, v in files.items() if k in filt.files}
    pages = {}
    for fk, ok, failed in con.execute(
            "SELECT file_key, SUM(status = 'ok'), SUM(status = 'failed') FROM pages GROUP BY file_key"):
        pages[fk] = {"ok": ok or 0, "failed": failed or 0}
    colour = _colour_counts(con, filt, idx)
    nodes = _node_counts(con, filt)
    rows = []
    for fk, f in files.items():
        f["pages"] = pages.get(fk, {"ok": 0, "failed": 0})
        f["metrics"] = _metrics(colour.get(fk, {}), nodes.get(fk, {}), idx)
        rows.append(f)
    # Сначала там, где хуже: больше всего «плохих» ячеек, потом больше левых цветов.
    rows.sort(key=lambda r: (-sum(1 for v in r["metrics"]["levels"].values() if v == "bad"),
                             -(r["metrics"]["stray"] or 0), r["name"] or ""))

    # Общие числа — по всем файлам сразу, а не сумма процентов.
    all_c = {"uses": 0, "raw": 0, "near": 0, "alpha": 0, "off": 0, "unbound": 0}
    for m in colour.values():
        for k in all_c:
            all_c[k] += m.get(k, 0)
    items = inventory.colours(con, filt, idx)
    all_c["colours"] = len(items)
    st = inventory.stray(items)
    for k in ("near", "alpha", "off", "unbound"):
        all_c[k] = len(st[k])
    all_n = {k: sum(n.get(k, 0) for n in nodes.values()) for k in ("layers", "texts", "text_nostyle", "generic")}
    totals = _metrics(all_c, all_n, idx)
    totals["bound_pct"] = None if not totals["uses"] else round(100 - (totals["raw_pct"] or 0), 1)

    trend = _trend(con) if filt.is_default() else None
    return {"filter": filt.to_dict(), "tokens": bool(idx), "totals": totals, "files": rows,
            "levels": LEVELS, "trend": trend}


# ---------------------------------------------------------------- история

def snapshot(con, idx: Index) -> str:
    """Записывает числа по каждому файлу при фильтрах по умолчанию. Вызывается после обновления."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data = overview(con, Filter(), idx)
    with con:
        for f in data["files"]:
            m = {k: v for k, v in f["metrics"].items() if k != "levels"}
            con.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?)", (now, f["file_key"], json.dumps(m)))
        tot = {k: v for k, v in data["totals"].items() if k != "levels"}
        con.execute("INSERT OR REPLACE INTO snapshots VALUES (?, '*', ?)", (now, json.dumps(tot)))
    return now


def _trend(con) -> dict | None:
    """Разница между двумя последними снимками: по файлам и в целом."""
    stamps = [r[0] for r in con.execute("SELECT DISTINCT taken_at FROM snapshots ORDER BY taken_at DESC LIMIT 2")]
    if len(stamps) < 2:
        return None
    cur, prev = stamps
    def load(ts):
        return {fk: json.loads(m) for fk, m in con.execute(
            "SELECT file_key, metrics FROM snapshots WHERE taken_at = ?", (ts,))}
    a, b = load(cur), load(prev)
    diff = {}
    for fk, m in a.items():
        old = b.get(fk)
        if not old:
            continue
        diff[fk] = {k: (v - old[k]) for k, v in m.items()
                    if isinstance(v, (int, float)) and isinstance(old.get(k), (int, float))}
    return {"since": prev, "now": cur, "by_file": diff}
