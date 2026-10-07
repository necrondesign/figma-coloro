"""Метки, которые ставятся при загрузке, и разбор ссылок.

Здесь ничего не решается — только распознаётся. Архивная страница остаётся в базе с меткой,
а учитывать её или нет, выбирает фильтр при просмотре.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

# Как люди называют архив. Последний вариант — с кириллической «с» внутри латиницы:
# глазом не отличить, а простое сравнение строк его пропускает.
ARCHIVE_MARKERS = ("archive", "arhive", "архив", "arсhive")


def is_archive(name: str) -> bool:
    """Похожа ли страница или файл на архив — по названию, без учёта регистра."""
    low = (name or "").lower()
    return any(m in low for m in ARCHIVE_MARKERS)


def name_matches(name: str, patterns) -> bool:
    """Подходит ли название под любой из образцов — по вхождению, без учёта регистра.
    Пустой список образцов означает «подходит всё»."""
    pats = [p.strip().lower() for p in (patterns or []) if p and p.strip()]
    if not pats:
        return True
    low = (name or "").lower()
    return any(p in low for p in pats)


_KEY_RE = re.compile(r"^[A-Za-z0-9]+$")


class LinkError(ValueError):
    pass


def parse_link(url: str) -> tuple[str, str | None]:
    """Ссылка на Figma → (ключ файла, id узла или None).

    Понимает /file/, /design/, /proto/, /board/ и ветки (/branch/КЛЮЧ — берётся ключ ветки).
    id узла в ссылке пишется через дефис, в API — через двоеточие.
    """
    raw = (url or "").strip()
    u = urlparse(raw)
    host = (u.netloc or "").lower()
    # Ссылка на чужой сайт — не файл Figma, даже если её путь похож на ключ.
    if host and not (host == "figma.com" or host.endswith(".figma.com")):
        raise LinkError("This is not a Figma link")
    parts = [p for p in u.path.split("/") if p]
    key = None
    for i, p in enumerate(parts):
        if p in ("file", "design", "proto", "board") and i + 1 < len(parts):
            key = parts[i + 1]
            # Ветка живёт отдельным файлом со своим ключом.
            if i + 3 < len(parts) and parts[i + 2] == "branch":
                key = parts[i + 3]
            break
    if not key and len(parts) == 1 and _KEY_RE.match(parts[0]):
        key = parts[0]
    if not key or not _KEY_RE.match(key):
        raise LinkError("This does not look like a Figma file link")
    node = (parse_qs(u.query).get("node-id") or [None])[0]
    if node:
        node = node.replace("-", ":")
    return key, node
