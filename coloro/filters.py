"""Фильтры: что учитывать при просмотре.

Загрузка хранит всё, а здесь решается, что из этого считать. Один и тот же фильтр
применяется ко всем экранам — общей картине, левым цветам, поиску, — поэтому числа
на разных экранах всегда сходятся.

Состояния по умолчанию выбраны по одному правилу: считать то, что видно на экране.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .textnorm import norm

# Краска → страница → файл. Поля слоя, по которым фильтруют, лежат у самой краски.
JOIN = (" JOIN pages pg ON pg.file_key = p.file_key AND pg.page_id = p.page_id"
        " JOIN files f ON f.file_key = p.file_key")
# Слой → страница → файл.
NODE_JOIN = (" JOIN pages pg ON pg.file_key = n.file_key AND pg.page_id = n.page_id"
             " JOIN files f ON f.file_key = n.file_key")
# То же, но слои — внешним циклом. Для запросов, которые проходят по всем слоям: подряд по
# таблице это в разы быстрее, чем от страниц через индекс с поиском каждого слоя по ключу.
# На 4,3 млн слоёв поиск текста — 0,6 с вместо 2,9.
NODE_SCAN = (" CROSS JOIN pages pg ON pg.file_key = n.file_key AND pg.page_id = n.page_id"
             " CROSS JOIN files f ON f.file_key = n.file_key")


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

    def where(self, paints: bool = False) -> tuple[str, list]:
        """Условие для запроса, в котором есть n (слои), pg (страницы) и f (файлы).

        paints=True — запрос по краскам p без слоёв: поля слоя берутся у краски."""
        x = "p" if paints else "n"
        w, a = ["1=1"], []
        if not self.hidden:
            w.append(f"{x}.hid = 0")
        if not self.archive:
            w.append("pg.archived = 0")
        if not self.instances:
            w.append("p.inst = 0" if paints else "n.pinst IS NULL")
        if self.pages:
            # norm(), а не lower(): встроенная lower() не опускает регистр кириллицы, и
            # «Служебное» не нашлось бы по «служ».
            w.append("(" + " OR ".join("norm(pg.name) LIKE ?" for _ in self.pages) + ")")
            a += [f"%{norm(p)}%" for p in self.pages]
        for s in self.skip_sections:
            w.append(f"({x}.sect IS NULL OR {x}.sect NOT IN (SELECT id FROM vals WHERE norm(v) LIKE ?))")
            a.append(f"%{norm(s)}%")
        if self.files:
            w.append(f"{x}.file_key IN (" + ",".join("?" * len(self.files)) + ")")
            a += self.files
        if self.since:
            w.append(f"{x}.first_seen >= ?")
            a.append(self.since)
        if self.modified_since:
            w.append("f.last_modified >= ?")
            a.append(self.modified_since)
        return " AND ".join(w), a
