"""Фильтры: что учитывать при просмотре.

Загрузка хранит всё, а здесь решается, что из этого считать. Один и тот же фильтр
применяется ко всем экранам — общей картине, левым цветам, поиску, — поэтому числа
на разных экранах всегда сходятся.

Состояния по умолчанию выбраны по одному правилу: считать то, что видно на экране.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Таблицы, которые соединяет каждый запрос: краска → слой → страница → файл.
JOIN = (" JOIN nodes n ON n.file_key = p.file_key AND n.id = p.node_id"
        " JOIN pages pg ON pg.file_key = n.file_key AND pg.page_id = n.page_id"
        " JOIN files f ON f.file_key = n.file_key")
NODE_JOIN = (" JOIN pages pg ON pg.file_key = n.file_key AND pg.page_id = n.page_id"
             " JOIN files f ON f.file_key = n.file_key")


def _list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = v.split(",")
    return [x.strip() for x in v if x and str(x).strip()]


@dataclass
class Filter:
    hidden: bool = False                 # учитывать скрытые слои
    archive: bool = False                # учитывать архивные страницы
    instances: bool = True               # учитывать слои внутри компонентов (они видны на экране)
    pages: list[str] = field(default_factory=list)          # только страницы с такими словами в названии
    skip_sections: list[str] = field(default_factory=list)  # не учитывать слои в секциях с такими словами
    files: list[str] = field(default_factory=list)          # только эти файлы (ключи)
    since: str | None = None             # только слои, появившиеся не раньше этой даты
    modified_since: str | None = None    # только файлы, изменённые не раньше этой даты

    @classmethod
    def from_query(cls, q: dict) -> "Filter":
        def one(k):
            v = q.get(k)
            return v[0] if isinstance(v, list) else v

        def flag(k):
            return str(one(k) or "").lower() in ("1", "true", "yes", "on")

        return cls(
            hidden=flag("hidden"), archive=flag("archive"),
            instances=(str(one("instances") or "1").lower() not in ("0", "false", "no", "off")),
            pages=_list(one("pages")), skip_sections=_list(one("skip")),
            files=_list(one("files")),
            since=(one("since") or None), modified_since=(one("modified_since") or None),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def is_default(self) -> bool:
        return self == Filter()

    def where(self) -> tuple[str, list]:
        """Условие для запроса, в котором есть n (слои), pg (страницы) и f (файлы)."""
        w, a = ["1=1"], []
        if not self.hidden:
            w.append("n.hid = 0")
        if not self.archive:
            w.append("pg.archived = 0")
        if not self.instances:
            w.append("n.pinst IS NULL")
        if self.pages:
            w.append("(" + " OR ".join("lower(pg.name) LIKE ?" for _ in self.pages) + ")")
            a += [f"%{p.lower()}%" for p in self.pages]
        for s in self.skip_sections:
            w.append("(n.sect IS NULL OR n.sect NOT IN (SELECT id FROM vals WHERE lower(v) LIKE ?))")
            a.append(f"%{s.lower()}%")
        if self.files:
            w.append("n.file_key IN (" + ",".join("?" * len(self.files)) + ")")
            a += self.files
        if self.since:
            w.append("n.first_seen >= ?")
            a.append(self.since)
        if self.modified_since:
            w.append("f.last_modified >= ?")
            a.append(self.modified_since)
        return " AND ".join(w), a
