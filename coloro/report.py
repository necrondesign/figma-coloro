"""Отчёт одним файлом: общая картина и списки того, что поправить, — чтобы переслать.

Это обычная HTML-страница без внешних файлов и скриптов: открывается в любом браузере,
печатается, прикладывается к письму. Числа — те же, что на экранах, при тех же фильтрах.
Ссылки ведут прямо на экраны в Figma.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from . import effects, health, inventory, scales, search, typography
from .filters import Filter
from .tokens import Index

TOP = 40            # сколько строк в каждом списке
LINKED = 10         # у скольких первых строк показывать экраны со ссылками
SCREENS = 3         # сколько экранов на строку

STATUS = {"near": "почти токен", "alpha": "другая прозрачность", "off": "мимо системы",
          "unbound": "не привязан"}
LEVEL_NAMES = {"good": "хорошо", "fair": "есть что поправить", "bad": "плохо"}


def _n(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.1f}".replace(",", " ").replace(".", ",")
    return f"{int(v):,}".replace(",", " ")


def _pct(v) -> str:
    return "—" if v is None else _n(round(v, 1)) + "%"


def _filter_text(f: Filter) -> str:
    parts = [f"скрытые слои — {'да' if f.hidden else 'нет'}",
             f"архивные страницы — {'да' if f.archive else 'нет'}",
             f"слои внутри компонентов — {'да' if f.instances else 'нет'}"]
    if f.pages:
        parts.append("только страницы: " + ", ".join(f.pages))
    if f.skip_sections:
        parts.append("без секций: " + ", ".join(f.skip_sections))
    if f.since:
        parts.append(f"слои, появившиеся с {f.since}")
    if f.files:
        parts.append(f"файлов выбрано: {len(f.files)}")
    return "Учитывались: " + "; ".join(parts) + "."


def _links(res: dict) -> str:
    out = []
    for g in res.get("items", [])[:SCREENS]:
        label = f"{g['file']} › {g['page']} › {g['screen']}"
        out.append(f'<a href="{escape(g["link"])}">{escape(label)}</a> <span class="m">({_n(g["count"])})</span>')
    more = res.get("total", 0) - len(out)
    if more > 0:
        out.append(f'<span class="m">и ещё {_n(more)}</span>')
    return "<br>".join(out)


def _table(head: list[str], rows: list[list[str]], empty: str = "Ничего не нашлось.") -> str:
    if not rows:
        return f'<p class="m">{escape(empty)}</p>'
    th = "".join(f"<th>{escape(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<div class='tw'><table><tr>{th}</tr>{body}</table></div>"


def build(con, filt: Filter, idx: Index) -> str:
    o = health.overview(con, filt, idx)
    t = o["totals"]
    now = datetime.now(timezone.utc).astimezone()
    sections = []

    # --- общая картина
    tiles = [("Цвета из системы", _pct(t.get("bound_pct")), "применений через токен или стиль"),
             ("Левых цветов", _n(t.get("stray")) if o["tokens"] else "—",
              "почти токен, другая прозрачность, мимо системы" if o["tokens"] else "нужен справочник токенов"),
             ("Набрано вручную", _pct(t.get("raw_pct")), "применений цвета без токена и стиля"),
             ("Тексты без стиля", _pct(t.get("text_nostyle_pct")), "у положенных на экран вручную"),
             ("Мимо шкалы", _pct(t.get("scale_off_pct")), "отступов, скруглений и обводок"),
             ("Безымянные", _n(t.get("generic")), "кадры и группы с названием по умолчанию")]
    sections.append("<h2 id='summary'>Общая картина</h2><div class='tiles'>" + "".join(
        f"<div class='tile'><div class='t'>{escape(a)}</div><div class='v'>{b}</div><div class='m'>{escape(c)}</div></div>"
        for a, b, c in tiles) + "</div>")

    cols = [("stray", "Левые цвета", False), ("unbound", "Не привязаны", False), ("raw_pct", "Вручную", True),
            ("text_nostyle_pct", "Тексты без стиля", True), ("scale_off_pct", "Мимо шкалы", True),
            ("generic", "Безымянные", False)]
    rows = []
    for f in o["files"]:
        m = f["metrics"]
        cells = [f"<b>{escape(f['name'] or f['file_key'])}</b><br><span class='m'>изменён {escape((f.get('last_modified') or '')[:10])}</span>"]
        for key, _title, is_pct in cols:
            lv = m["levels"].get(key) or "none"
            text = _pct(m.get(key)) if is_pct else _n(m.get(key))
            cells.append(f"<span class='lv lv-{lv}' title='{escape(LEVEL_NAMES.get(lv, ''))}'>{text}</span>")
        rows.append(cells)
    sections.append("<h2 id='files'>Где хорошо и где плохо</h2>"
                    "<p class='m'>Сначала файлы, где хуже. Цвет ячейки: зелёный — хорошо, жёлтый — есть что поправить, красный — плохо.</p>"
                    + _table(["Файл"] + [c[1] for c in cols], rows))

    # --- левые цвета
    if o["tokens"]:
        items = [i for i in inventory.colours(con, filt, idx) if i["status"] in ("near", "alpha", "off")][:TOP]
        rows = []
        for n, i in enumerate(items):
            near = i.get("nearest") or {}
            hint = f"ближе всего <b>{escape(near.get('name', ''))}</b> {escape(near.get('label', ''))}" if near else ""
            where = _links(inventory.screens(con, filt, i["color"], i["alpha"], limit=SCREENS)) if n < LINKED else ""
            rows.append([f"<span class='sw' style='background:#{i['color']};opacity:{i['alpha'] / 100}'></span> <code>{escape(i['label'])}</code>",
                         escape(STATUS.get(i["status"], i["status"])), hint, _n(i["uses"]), _n(i["screens"]), where])
        sections.append("<h2 id='colours'>Левые цвета</h2>"
                        "<p class='m'>Цвета, которых нет среди токенов: почти токен — заменить на токен; другая прозрачность — "
                        "нужен токен этой прозрачности; мимо системы — добавить в систему или заменить.</p>"
                        + _table(["Цвет", "Что с ним", "Токен", "Применений", "Экранов", "Где"], rows))
    else:
        sections.append("<h2 id='colours'>Левые цвета</h2><p class='m'>Справочник токенов не загружен — сравнивать не с чем.</p>")

    # --- типографика
    ty = typography.fonts(con, filt)
    items = [i for i in ty["items"] if i["status"] in ("unbound", "near", "off")][:TOP]
    rows = []
    for n, i in enumerate(items):
        nearest = i.get("nearest") or {}
        what = {"unbound": "как стиль " + ", ".join(i.get("styles") or []),
                "near": f"почти стиль {nearest.get('name', '')}",
                "off": f"мимо системы{(' — ближе всего ' + nearest.get('name', '')) if nearest else ''}"}[i["status"]]
        where = ""
        if n < LINKED // 2:
            c, a, _ = search.condition("font", {"font": i["font_id"]}, con)
            where = _links(search.screens(con, filt, c, a, limit=SCREENS))
        rows.append([escape(i["label"]), escape(what), _n(i["uses"]), _n(i["screens"]), where])
    sections.append("<h2 id='type'>Тексты без стиля</h2>"
                    f"<p class='m'>Система — {_n(len(ty['styles']))} стилей, выведенных из самих макетов. Тексты внутри компонентов не считаются.</p>"
                    + _table(["Шрифт", "Что с ним", "Текстов", "Экранов", "Где"], rows))

    # --- отступы
    sc = scales.report(con, filt)
    names = {"spacing": "Отступы", "radius": "Скругления", "stroke": "Обводки"}
    parts = []
    for g, d in sc.items():
        items = [i for i in d["items"] if i["status"] in ("near", "off")][:TOP // 2]
        rows = []
        for n, i in enumerate(items):
            where = ""
            if n < LINKED // 2:
                c, a, _ = search.condition("prop", {"group": g, "value": i["value"]}, con)
                where = _links(search.screens(con, filt, c, a, limit=SCREENS))
            rows.append([f"{_n(i['value'])} px", "почти шкала" if i["status"] == "near" else "мимо шкалы",
                         f"{_n(i['nearest'])} px", _n(i["uses"]), _n(i["screens"]), where])
        src = ("шкала из переменных: " + " · ".join(_n(v["value"]) for v in d["scale"])) if d["source"] == "variables" \
            else "переменных нет — сравнение с привычной сеткой"
        tt = d["totals"]
        parts.append(f"<h3>{names[g]}</h3><p class='m'>{escape(src)}. Через переменную — {_n(tt['bound'])}, "
                     f"почти шкала — {_n(tt['near'])}, мимо шкалы — {_n(tt['off'])}.</p>"
                     + _table(["Значение", "Что с ним", "Ближайшее", "Раз", "Экранов", "Где"], rows))
    sections.append("<h2 id='spacing'>Отступы, скругления, обводки</h2>" + "".join(parts))

    # --- эффекты
    ef = effects.report(con, filt)
    rows = [[escape(i["label"]) + (f" <code>#{escape(i['color'])}</code>" if i.get("color") else ""),
             {"unbound": "не привязан", "near": "почти стиль", "off": "мимо системы"}[i["status"]],
             escape(", ".join(i.get("styles") or [])), _n(i["uses"]), _n(i["screens"])]
            for i in ef["items"][:TOP]]
    sections.append("<h2 id='effects'>Тени и эффекты</h2>"
                    f"<p class='m'>Со стилем — {_n(ef['totals']['styled'])}, вручную — {_n(sum(i['uses'] for i in ef['items']))}.</p>"
                    + _table(["Эффект", "Что с ним", "Стиль", "Слоёв", "Экранов"], rows))

    # --- картинки
    im = effects.images(con, filt, limit=TOP)
    rows = [[escape(i["name"]), _n(i["uses"]), _n(i["screens"]), _n(i["files"])] for i in im["items"] if i["uses"] > 1][:TOP // 2]
    sections.append("<h2 id='images'>Картинки</h2>"
                    f"<p class='m'>{_n(im['total'])} картинок в {_n(im['total_uses'])} местах; {_n(im['once'])} стоят по одному разу. Самые повторяющиеся:</p>"
                    + _table(["Слой", "Мест", "Экранов", "Файлов"], rows))

    # --- компоненты
    comp = search.components(con, filt)
    rows = [[escape(g["title"]) + (" <span class='m'>из библиотеки</span>" if g["remote"] else ""),
             _n(g["instances"]), _n(g["overridden"]), _n(g["screens"]), _n(g["files"])] for g in comp["items"][:TOP]]
    det = search.detached(con, filt, limit=TOP)
    drows = [[f'<a href="{escape(d["link"])}">{escape(d["name"])}</a>', escape(f"{d['file']} › {d['page']} › {d['screen']}")]
             for d in det["items"]]
    sections.append("<h2 id='components'>Компоненты</h2>"
                    + _table(["Компонент", "Инстансов", "Изменено", "Экранов", "Файлов"], rows)
                    + "<h3>Похожи на отвязанные копии</h3><p class='m'>Кадры с именем компонента, но не инстансы. Это догадка по имени.</p>"
                    + _table(["Кадр", "Где"], drows))

    title = "coloro — отчёт " + now.strftime("%d.%m.%Y")
    nav = " · ".join(f"<a href='#{a}'>{b}</a>" for a, b in (
        ("summary", "Общая картина"), ("files", "Файлы"), ("colours", "Цвета"), ("type", "Тексты"),
        ("spacing", "Отступы"), ("effects", "Эффекты"), ("images", "Картинки"), ("components", "Компоненты")))
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
body{{font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#1e1e1e;background:#fff;margin:0;padding:32px 16px}}
main{{max-width:1100px;margin:0 auto}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:18px;margin:36px 0 8px;padding-top:8px;border-top:1px solid #e6e6e6}}
h3{{font-size:15px;margin:20px 0 6px}}
.m{{color:#6b6b6b;font-size:12.5px}} a{{color:#0c6fc2}} code{{font:12px ui-monospace,Menlo,monospace;white-space:nowrap}}
nav{{margin:10px 0 0;font-size:13px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}}
.tile{{background:#f5f5f5;border-radius:8px;padding:10px 12px}} .tile .t{{font-size:12px;color:#6b6b6b}} .tile .v{{font-size:22px;font-weight:600}}
.tw{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:13px}} th{{text-align:left;font-weight:500;color:#6b6b6b;border-bottom:1px solid #e0e0e0;padding:6px 8px}}
td{{border-bottom:1px solid #f0f0f0;padding:6px 8px;vertical-align:top}}
.lv{{display:inline-block;min-width:52px;padding:2px 6px;border-radius:4px;text-align:right}}
.lv-good{{background:#e3f5ea;color:#17703d}} .lv-fair{{background:#fdf1d8;color:#8a5a00}} .lv-bad{{background:#fde4e2;color:#a3261c}}
.sw{{display:inline-block;width:14px;height:14px;border-radius:3px;border:1px solid #ddd;vertical-align:-2px}}
@media print{{h2{{break-after:avoid}} tr{{break-inside:avoid}} a{{color:inherit}}}}
</style></head><body><main>
<h1>{escape(title)}</h1>
<p class="m">{_n(len(o['files']))} файлов · {_n(t.get('layers'))} слоёв · {_n(t.get('uses'))} применений цвета · собран {now.strftime('%d.%m.%Y %H:%M')}</p>
<p class="m">{escape(_filter_text(filt))}</p>
<nav>{nav}</nav>
{''.join(sections)}
<p class="m" style="margin-top:40px">Сделано в coloro.</p>
</main></body></html>"""
