"""Нечёткий поиск: опечатки, другая раскладка, транслит.

Ничего не угадывается вслепую: каждый запасной вариант слова берётся только из словаря проекта —
слов, которые действительно есть в его макетах (тексты, названия слоёв, страниц и файлов).
Поэтому «Onbaording» находит «Onboarding», «ghbdtn» — «привет», «knopka» — «кнопка», но
не тянет за собой случайные совпадения: слова, которого нет в макетах, искать незачем.
"""

from __future__ import annotations

import re
from collections import Counter

from .textnorm import norm, stem

_WORD = re.compile(r"[0-9a-zа-яё]+", re.I)
MAX_ALTS = 8                                     # запасных слов на одно слово запроса

# ---------------------------------------------------------------- раскладка

_EN = "`qwertyuiop[]asdfghjkl;'zxcvbnm,."
_RU = "ёйцукенгшщзхъфывапролджэячсмитьбю"
_TO_RU = dict(zip(_EN, _RU))
_TO_EN = dict(zip(_RU, _EN))


def other_layout(word: str) -> str | None:
    """Слово, набранное не в той раскладке: «ghbdtn» → «привет», «руддщ» → «hello»."""
    if re.search("[а-яё]", word):
        out = "".join(_TO_EN.get(c, c) for c in word)
    else:
        out = "".join(_TO_RU.get(c, c) for c in word)
    return out if out != word else None


# ---------------------------------------------------------------- транслит

_CYR_LAT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
            "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
            "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
            "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"}
_LAT_CYR = [("shch", "щ"), ("sch", "щ"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"),
            ("yu", "ю"), ("ya", "я"), ("yo", "ё"), ("ye", "е"), ("ee", "и"), ("oo", "у"), ("ck", "к"),
            ("ph", "ф"), ("th", "т"), ("qu", "кв"), ("a", "а"), ("b", "б"), ("c", "к"), ("d", "д"),
            ("e", "е"), ("f", "ф"), ("g", "г"), ("h", "х"), ("i", "и"), ("j", "дж"), ("k", "к"), ("l", "л"),
            ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("q", "к"), ("r", "р"), ("s", "с"), ("t", "т"),
            ("u", "у"), ("v", "в"), ("w", "в"), ("x", "кс"), ("y", "й"), ("z", "з")]


def translit(word: str) -> str | None:
    """Кириллица ↔ латиница по звучанию: «кнопка» → «knopka», «onboarding» → «онбоардинг».
    Транслит неточен, поэтому дальше он сверяется со словарём с допуском (см. expand)."""
    if re.search("[а-яё]", word):
        out = "".join(_CYR_LAT.get(c, c) for c in word)
    else:
        out, i = [], 0
        while i < len(word):
            for lat, cyr in _LAT_CYR:
                if word.startswith(lat, i):
                    out.append(cyr)
                    i += len(lat)
                    break
            else:
                out.append(word[i])
                i += 1
        out = "".join(out)
    return out if out != word else None


# ---------------------------------------------------------------- расстояние

def distance(a: str, b: str, limit: int) -> int:
    """Сколько правок между словами: вставка, удаление, замена, перестановка соседних букв.
    Больше limit не считается — сразу limit + 1."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            best = min(best, v)
        if best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def allowed(word: str) -> int:
    """Сколько опечаток простить: в коротком слове одна буква меняет смысл."""
    n = len(word)
    return 0 if n < 4 else 1 if n < 8 else 2


# ---------------------------------------------------------------- словарь и подбор

def vocabulary(con, project: int | None) -> Counter:
    """Слова проекта и сколько раз каждое встречается."""
    scope = ("WHERE file_key IN (SELECT file_key FROM sources WHERE project_id = ?)" if project is not None else "")
    args = (project,) if project is not None else ()
    words: Counter = Counter()
    for sql in (f"SELECT tnorm, COUNT(*) FROM nodes {scope} {'AND' if scope else 'WHERE'} tnorm IS NOT NULL GROUP BY tnorm",
                f"SELECT nnorm, COUNT(*) FROM nodes {scope} GROUP BY nnorm",
                f"SELECT norm(name), 1 FROM pages {scope}",
                f"SELECT norm(name), 1 FROM files {scope}"):
        for text, n in con.execute(sql, args):
            for w in _WORD.findall(text or ""):
                if not w.isdigit():
                    words[w] += n
    return words


def _near(word: str, vocab: Counter, limit: int, prefix: bool = True) -> list[str]:
    """Слова словаря не дальше limit правок — целиком или началом (для недописанного слова)."""
    if limit <= 0:
        return []
    letters = set(word)
    out = []
    for v in vocab:
        if v == word or abs(len(v) - len(word)) > limit and not (prefix and len(v) > len(word)):
            continue
        # Быстрый отсев: слишком разный набор букв — не опечатка.
        if len(letters ^ set(v[:len(word) + limit])) > 2 * limit + 2:
            continue
        if distance(word, v, limit) <= limit or (
                prefix and len(v) > len(word) + limit and distance(word, v[:len(word)], limit) <= limit):
            out.append(v)
    return out


def expand(text: str, vocab: Counter, typos: bool, layout: bool) -> tuple[list[list[str]], list[str]]:
    """Запрос → для каждого слова список основ: своя первой, затем запасные из словаря.
    Второе — какие слова добавлены, чтобы показать человеку, что ещё искалось."""
    groups, also = [], []
    for m in _WORD.finditer(norm(text)):
        w = m.group(0)
        own = stem(w)
        if not own or any(own == g[0] for g in groups):
            continue
        alts: list[str] = []
        if not w.isdigit():
            found: list[str] = []
            if layout:
                lw = other_layout(w)
                if lw and lw in vocab:
                    found.append(lw)
                tw = translit(w)
                if tw:
                    found += [tw] if tw in vocab else _near(tw, vocab, max(1, len(tw) // 4))
            if typos:
                # Опечатки и в запросе, и в самих макетах: «Onbording» в названии слоя тоже найдётся.
                found += _near(w, vocab, allowed(w))
            seen = set()
            for v in sorted(found, key=lambda v: -vocab.get(v, 0)):
                s = stem(v)
                if s != own and s not in seen and not s.startswith(own):
                    seen.add(s)
                    alts.append(s)
                    also.append(v)
                if len(alts) >= MAX_ALTS:
                    break
        groups.append([own] + alts)
    return groups, also
