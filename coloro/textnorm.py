"""Нормализация текста и основы слов для поиска.

Поиск должен находить «купить» по запросу «купите», а «кнопки» — по «кнопка». Для этого
у каждого слова берётся основа: русская — по алгоритму Snowball (Портер для русского языка),
английская — снятием частых окончаний. Совпадение — по вхождению основы, поэтому слова можно
писать в любом порядке и в любой форме.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[0-9a-zа-яё]+", re.I)


def norm(text: str | None) -> str:
    """Строка для поиска: нижний регистр, «ё» как «е», пробелы схлопнуты."""
    if not text:
        return ""
    return " ".join(text.lower().replace("ё", "е").split())


# ---------------------------------------------------------------- русский: Snowball

_VOWELS = "аеиоуыэюя"
_PERF_GERUND = (("в", "вши", "вшись"), ("ив", "ивши", "ившись", "ыв", "ывши", "ывшись"))
_ADJECTIVE = ("ее", "ие", "ые", "ое", "ими", "ыми", "ей", "ий", "ый", "ой", "ем", "им", "ым", "ом",
              "его", "ого", "ему", "ому", "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею")
_PARTICIPLE = (("ем", "нн", "вш", "ющ", "щ"), ("ивш", "ывш", "ующ"))
_REFLEXIVE = ("ся", "сь")
_VERB = (("ла", "на", "ете", "йте", "ли", "й", "л", "ем", "н", "ло", "но", "ет", "ют", "ны", "ть", "ешь", "нно"),
         ("ила", "ыла", "ена", "ейте", "уйте", "ите", "или", "ыли", "ей", "уй", "ил", "ыл", "им", "ым", "ен",
          "ило", "ыло", "ено", "ят", "ует", "уют", "ит", "ыт", "ены", "ить", "ыть", "ишь", "ую", "ю"))
_NOUN = ("а", "ев", "ов", "ие", "ье", "е", "иями", "ями", "ами", "еи", "ии", "и", "ией", "ей", "ой", "ий", "й",
         "иям", "ям", "ием", "ем", "ам", "ом", "о", "у", "ах", "иях", "ях", "ы", "ь", "ию", "ью", "ю", "ия", "ья", "я")
_SUPERLATIVE = ("ейше", "ейш")
_DERIVATIONAL = ("ость", "ост")


def _regions(w: str) -> tuple[int, int]:
    """Начало RV (после первой гласной) и R2 — по правилам Snowball."""
    rv = next((i + 1 for i, c in enumerate(w) if c in _VOWELS), len(w))
    r1 = len(w)
    for i in range(1, len(w)):
        if w[i] not in _VOWELS and w[i - 1] in _VOWELS:
            r1 = i + 1
            break
    r2 = len(w)
    for i in range(r1 + 1, len(w)):
        if w[i] not in _VOWELS and w[i - 1] in _VOWELS:
            r2 = i + 1
            break
    return rv, r2


def _strip(word: str, start: int, groups, need_a: bool = False) -> str | None:
    """Снимает самое длинное окончание из списка, если оно целиком в области от start.
    need_a — окончания первой группы снимаются, только если перед ними «а» или «я»."""
    best = None
    for suf in sorted(groups, key=len, reverse=True):
        if word.endswith(suf) and len(word) - len(suf) >= start:
            if need_a:
                prev = word[len(word) - len(suf) - 1:len(word) - len(suf)]
                if prev not in ("а", "я"):
                    continue
            best = word[:-len(suf)]
            break
    return best


def _strip2(word: str, start: int, pair) -> str | None:
    """Две группы окончаний: первая — после «а»/«я», вторая — без условия. Берётся самое длинное."""
    candidates = []
    a = _strip(word, start, pair[0], need_a=True)
    if a is not None:
        candidates.append(a)
    b = _strip(word, start, pair[1])
    if b is not None:
        candidates.append(b)
    return min(candidates, key=len) if candidates else None


def stem_ru(word: str) -> str:
    w = word.lower().replace("ё", "е")
    rv, r2 = _regions(w)
    # Шаг 1
    s = _strip2(w, rv, _PERF_GERUND)
    if s is None:
        r = _strip(w, rv, _REFLEXIVE)
        if r is not None:
            w = r
        s = _strip(w, rv, _ADJECTIVE)
        if s is not None:
            p = _strip2(s, rv, _PARTICIPLE)
            if p is not None:
                s = p
        else:
            s = _strip2(w, rv, _VERB)
            if s is None:
                s = _strip(w, rv, _NOUN)
    if s is not None:
        w = s
    # Шаг 2
    if w.endswith("и") and len(w) - 1 >= rv:
        w = w[:-1]
    # Шаг 3
    d = _strip(w, r2, _DERIVATIONAL)
    if d is not None:
        w = d
    # Шаг 4
    if w.endswith("нн") and len(w) - 1 >= rv:
        w = w[:-1]
    else:
        sp = _strip(w, rv, _SUPERLATIVE)
        if sp is not None:
            w = sp
            if w.endswith("нн"):
                w = w[:-1]
        elif w.endswith("ь") and len(w) - 1 >= rv:
            w = w[:-1]
    return w


# ---------------------------------------------------------------- английский: лёгкий

_EN_SUFFIXES = ("ational", "ization", "fulness", "iveness", "ations", "ation", "ments", "ement", "ness",
                "ings", "ing", "ies", "ied", "ers", "est", "ful", "ous", "ive", "ize", "ise", "ment",
                "ed", "er", "es", "ly", "s")


def stem_en(word: str) -> str:
    w = word.lower()
    for suf in _EN_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            if suf in ("ies", "ied"):
                w += "y"
            break
    return w


def stem(word: str) -> str:
    """Основа слова. Короче трёх букв основа почти всё совпадает со всем, поэтому
    короткие слова и числа берутся как есть."""
    w = norm(word)
    if len(w) <= 3 or w.isdigit():
        return w
    s = stem_ru(w) if re.search("[а-я]", w) else stem_en(w)
    return s if len(s) >= 3 else w


def query_stems(q: str) -> list[str]:
    """Запрос → основы слов, без повторов, в порядке ввода."""
    out = []
    for m in _WORD.finditer(q or ""):
        s = stem(m.group(0))
        if s and s not in out:
            out.append(s)
    return out
