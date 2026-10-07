"use strict";
/* coloro — экраны: общая картина, цвета, источники, настройки.
   Любая строка из Figma проходит через esc() до попадания в разметку. */

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("ru-RU"));
const pct = (n) => (n == null ? "—" : (Math.round(n * 10) / 10).toLocaleString("ru-RU") + "%");
const plural = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? few : many;
};
const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
function day(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const s = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return d.getFullYear() === new Date().getFullYear() ? s : `${s} ${d.getFullYear()}`;
}
function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 90) return "только что";
  if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  return day(iso);
}

function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove("show"), 3200);
}

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (e) { /* пустой ответ */ }
  if (!r.ok) throw new Error(data.error || `сервер ответил ${r.status}`);
  return data;
}

/* ───────────────────── фильтры ───────────────────── */

const DEFAULT = { hidden: false, archive: false, instances: true, pages: "", skip: "", files: "", since: "" };
let filt = { ...DEFAULT };
try { filt = { ...DEFAULT, ...JSON.parse(localStorage.getItem("coloro.filter") || "{}") }; } catch (e) { /* по умолчанию */ }
const isDefault = () => Object.keys(DEFAULT).every((k) => filt[k] === DEFAULT[k]);
function saveFilter() { try { localStorage.setItem("coloro.filter", JSON.stringify(filt)); } catch (e) { /* не страшно */ } }
function fq(extra = {}) {
  const q = new URLSearchParams();
  if (filt.hidden) q.set("hidden", "1");
  if (filt.archive) q.set("archive", "1");
  if (!filt.instances) q.set("instances", "0");
  for (const k of ["pages", "skip", "files", "since"]) if (filt[k]) q.set(k, filt[k]);
  for (const [k, v] of Object.entries(extra)) if (v !== undefined && v !== null && v !== "") q.set(k, v);
  const s = q.toString();
  return s ? "?" + s : "";
}
let fileNames = {};

function renderFilters(show) {
  const el = $("#filters");
  el.hidden = !show;
  if (!show) return;
  const fileChip = filt.files
    ? `<button class="chip on" data-clear="files" title="Показать все файлы">Файл: ${esc(fileNames[filt.files] || filt.files)} ✕</button>`
    : "";
  el.innerHTML = `
    <span class="lbl">Учитывать:</span>
    <button class="chip ${filt.hidden ? "on" : ""}" data-flag="hidden" title="Скрытые слои не рисуются на экране. Почти все они — выключенные слои внутри компонентов">Скрытые слои</button>
    <button class="chip ${filt.archive ? "on" : ""}" data-flag="archive" title="Страницы, в названии которых есть «архив» или «archive»">Архивные страницы</button>
    <button class="chip ${filt.instances ? "on" : ""}" data-flag="instances" title="Слои внутри компонентов видны на экране, но их цвета задаёт библиотека. Выключите, чтобы видеть только то, что положено на экран вручную">Внутри компонентов</button>
    <label class="chip ${filt.pages ? "on" : ""}" title="Только страницы с такими словами в названии, через запятую">Страницы <input data-text="pages" value="${esc(filt.pages)}" placeholder="все"></label>
    <label class="chip ${filt.skip ? "on" : ""}" title="Не учитывать слои внутри секций с такими словами в названии, через запятую">Без секций <input data-text="skip" value="${esc(filt.skip)}" placeholder="нет"></label>
    <label class="chip ${filt.since ? "on" : ""}" title="Только то, что появилось в макетах не раньше этой даты">С даты <input type="date" data-text="since" value="${esc(filt.since)}" style="width:118px"></label>
    ${fileChip}
    ${isDefault() ? "" : '<button class="chip reset" data-reset>Сбросить</button>'}`;
  el.querySelectorAll("[data-flag]").forEach((b) => (b.onclick = () => { filt[b.dataset.flag] = !filt[b.dataset.flag]; saveFilter(); route(); }));
  el.querySelectorAll("[data-text]").forEach((inp) => {
    inp.onchange = () => { filt[inp.dataset.text] = inp.value.trim(); saveFilter(); route(); };
    inp.onkeydown = (e) => { if (e.key === "Enter") inp.blur(); };
  });
  el.querySelectorAll("[data-clear]").forEach((b) => (b.onclick = () => { filt[b.dataset.clear] = ""; saveFilter(); route(); }));
  const r = el.querySelector("[data-reset]");
  if (r) r.onclick = () => { filt = { ...DEFAULT }; saveFilter(); route(); };
}

/* ───────────────────── обновление в фоне ───────────────────── */

let lastJob = null;
async function pollJob() {
  let st;
  try { st = await api("/api/state"); } catch (e) { return; }
  const j = st.job || {};
  const el = $("#job");
  if (j.running) {
    const cur = Object.entries(j.current || {}).map(([f, c]) => `${esc(f)} · ${c.index}/${c.total}`).join(", ");
    el.innerHTML = `Обновление: ${cur || "проверяем версии"} <button class="b quiet" id="stopJob">Остановить</button>`;
    $("#stopJob").onclick = async () => { await api("/api/stop", {}); toast("Останавливаем после текущей страницы"); };
  } else {
    el.textContent = "";
  }
  if (lastJob && lastJob.running && !j.running) {
    const reps = j.reports || [];
    const loaded = reps.reduce((n, r) => n + (r.pages_loaded || []).length, 0);
    const failed = reps.reduce((n, r) => n + (r.pages_failed || []).length + (r.status === "failed" ? 1 : 0), 0);
    toast(j.stopped ? "Остановлено. Загруженные страницы сохранены"
      : failed ? `Готово, но ${failed} ${plural(failed, "страница не загрузилась", "страницы не загрузились", "страниц не загрузились")} — подробности в «Источниках»`
      : loaded ? `Обновлено ${loaded} ${plural(loaded, "страница", "страницы", "страниц")}` : "Всё уже свежее — менять нечего");
    route();
  }
  lastJob = j;
  clearTimeout(pollJob.t);
  pollJob.t = setTimeout(pollJob, j.running ? 1500 : 8000);
}
async function startUpdate(body = {}) {
  try { await api("/api/update", body); toast("Обновление началось"); pollJob(); }
  catch (e) { toast(e.message); }
}

/* ───────────────────── общая картина ───────────────────── */

const LOWER_IS_BETTER = new Set(["stray", "raw", "raw_pct", "text_nostyle", "text_nostyle_pct", "generic", "near", "off", "unbound"]);
function delta(key, d) {
  if (d == null || d === 0) return "";
  const better = LOWER_IS_BETTER.has(key) ? d < 0 : d > 0;
  const n = Math.abs(Math.round(d * 10) / 10).toLocaleString("ru-RU");
  return `<span class="${better ? "down-good" : "up-bad"}">${d > 0 ? "↑" : "↓"} ${n}${key.endsWith("pct") ? "%" : ""} с прошлого обновления</span>`;
}

const COLUMNS = [
  { key: "stray", title: "Левые цвета", hint: "Почти токен, другая прозрачность и мимо системы", cat: "stray" },
  { key: "unbound", title: "Не привязаны", hint: "Цвет совпадает с токеном, но набран вручную", cat: "unbound" },
  { key: "raw_pct", title: "Вручную", hint: "Доля применений цвета без токена и стиля", cat: "all", pct: true },
  { key: "text_nostyle_pct", title: "Тексты без стиля", hint: "Доля текстов без текстового стиля — только тех, что положены на экран вручную: внутри компонентов стиль задаёт библиотека", pct: true, href: "#/typography?cat=all" },
  { key: "scale_off_pct", title: "Мимо шкалы", hint: "Доля отступов, скруглений и обводок, набранных вручную мимо шкалы или почти по ней, — у слоёв, положенных на экран вручную", pct: true, href: "#/spacing" },
  { key: "generic", title: "Безымянные", hint: "Кадры и группы с названием по умолчанию — Frame 12, Group 7 — только положенные на экран вручную: внутри компонентов названия задаёт библиотека" },
];

async function viewOverview(el, params, stale) {
  renderFilters(true);
  const [st, o] = await Promise.all([api("/api/state"), api("/api/overview" + fq())]);
  if (stale()) return;
  o.files.forEach((f) => (fileNames[f.file_key] = f.name));
  // Пусто — только когда нет ни ссылок, ни данных: файлы могли загрузить и командой coloro load.
  if (!st.sources.length && !o.files.length) {
    el.innerHTML = `<div class="empty"><b>Добавьте первый файл Figma</b><p>Вставьте ссылку на файл — coloro загрузит его и покажет, что в макетах хорошо, а что нет.</p><a class="b main" href="#/sources">Добавить ссылку</a></div>`;
    return;
  }
  if (!o.files.length) {
    el.innerHTML = `<div class="empty"><b>Файлы ещё не загружены</b><p>Ссылки добавлены, осталось загрузить их из Figma.</p><button class="b main" id="go">Загрузить</button></div>`;
    $("#go").onclick = () => startUpdate();
    return;
  }
  const t = o.totals;
  const tr = o.trend && o.trend.by_file && o.trend.by_file["*"];
  const notice = o.tokens ? "" : `<div class="notice">Чтобы видеть левые цвета, нужен справочник токенов вашей дизайн-системы. <a href="#/settings">Загрузить справочник</a></div>`;
  const task = (cat, title, n, sub) => `<div class="task" data-cat="${cat}"><b>${title}</b><span class="n">${fmt(n)}</span><span>${sub}</span></div>`;
  el.innerHTML = `
    ${notice}
    <div class="tasks">
      ${o.tokens ? task("near", "Почти токен", t.near, "заменить на токен") : ""}
      ${o.tokens ? task("alpha", "Другая прозрачность", t.alpha, "цвет токена с иной прозрачностью") : ""}
      ${o.tokens ? task("off", "Мимо системы", t.off, "добавить в систему или заменить") : ""}
      ${o.tokens ? task("unbound", "Не привязаны", t.unbound, "значение токена, набрано вручную") : ""}
      ${task("all", "Все цвета", t.colours, `${fmt(t.uses)} ${plural(t.uses, "применение", "применения", "применений")}`)}
    </div>
    <div class="tasks finds">
      <a class="task" href="#/search?mode=text"><b>Найти текст</b><span>слово или фраза в любой форме</span></a>
      <a class="task" href="#/search?mode=size"><b>Найти размер</b><span>например 56 × 56 с допуском</span></a>
      <a class="task" href="#/search?mode=colour"><b>Найти цвет</b><span>и похожие на него оттенки</span></a>
      <a class="task" href="#/typography"><b>Типографика</b><span>тексты без стиля против системы стилей</span></a>
      <a class="task" href="#/spacing"><b>Отступы и скругления</b><span>числа мимо шкалы и без переменных</span></a>
      <a class="task" href="#/effects"><b>Тени и эффекты</b><span>набранные вручную против стилей</span></a>
      <a class="task" href="#/images"><b>Картинки</b><span>что где стоит и что повторяется</span></a>
      <a class="task" href="#/components"><b>Компоненты</b><span>где стоят, какие варианты, что отвязано</span></a>
    </div>
    <div class="tiles">
      <div class="tile"><div class="t">Цвета из системы</div><div class="v">${pct(t.bound_pct)}</div><div class="d">${tr ? delta("bound_pct", tr.bound_pct) : "применений через токен или стиль"}</div></div>
      <div class="tile"><div class="t">Левых цветов</div><div class="v">${o.tokens ? fmt(t.stray) : "—"}</div><div class="d">${tr ? delta("stray", tr.stray) : o.tokens ? `почти ${fmt(t.near)} · прозрачность ${fmt(t.alpha)} · мимо ${fmt(t.off)}` : "нужен справочник токенов"}</div></div>
      <div class="tile"><div class="t">Набрано вручную</div><div class="v">${fmt(t.raw)}</div><div class="d">${tr ? delta("raw", tr.raw) : `${pct(t.raw_pct)} применений`}</div></div>
      <div class="tile"><div class="t">Тексты без стиля</div><div class="v">${fmt(t.text_nostyle)}</div><div class="d">${tr ? delta("text_nostyle", tr.text_nostyle) : `${pct(t.text_nostyle_pct)} текстов`}</div></div>
    </div>
    <h2>Где хорошо и где плохо</h2>
    <p class="sub">${fmt(o.files.length)} ${plural(o.files.length, "файл", "файла", "файлов")} — сначала те, где хуже. Нажмите на ячейку, чтобы увидеть места.</p>
    <div class="map-wrap"><table class="map">
      <colgroup><col style="width:30%">${COLUMNS.map(() => "<col>").join("")}</colgroup>
      <tr><th>Файл</th>${COLUMNS.map((c) => `<th title="${esc(c.hint)}">${c.title}</th>`).join("")}</tr>
      ${o.files.map((f) => {
        const m = f.metrics;
        const failed = f.pages.failed ? ` · <span style="color:var(--bad-tx)">${f.pages.failed} ${plural(f.pages.failed, "страница не загрузилась", "страницы не загрузились", "страниц не загрузились")}</span>` : "";
        return `<tr><td class="file" title="${esc(f.name)}">${esc(f.name)}<small>изменён ${esc(day(f.last_modified))}${failed}</small></td>${COLUMNS.map((c) => {
          const v = m[c.key];
          const lv = m.levels[c.key] || "none";
          const text = v == null ? "—" : c.pct ? pct(v) : fmt(v);
          const click = (c.cat || c.href) && v != null ? `class="cell lv-${lv}" data-file="${esc(f.file_key)}" ${c.cat ? `data-cat="${c.cat}"` : `data-href="${c.href}"`}` : `class="lv-${lv}"`;
          return `<td ${click} title="${esc(c.hint)}">${text}</td>`;
        }).join("")}</tr>`;
      }).join("")}
    </table></div>
    <div class="legend"><span><i class="lv-good"></i>хорошо</span><span><i class="lv-fair"></i>есть что поправить</span><span><i class="lv-bad"></i>плохо</span>
      ${o.trend ? `<span class="muted">· стрелки — с обновления ${esc(day(o.trend.since))}</span>` : isDefault() ? "" : '<span class="muted">· стрелки изменений видны при фильтрах по умолчанию</span>'}</div>`;
  el.querySelectorAll(".task").forEach((c) => (c.onclick = () => (location.hash = `#/colours?cat=${c.dataset.cat}`)));
  el.querySelectorAll("td.cell").forEach((c) => (c.onclick = () => {
    filt.files = c.dataset.file; saveFilter();
    location.hash = c.dataset.href || `#/colours?cat=${c.dataset.cat}`;
  }));
}

/* ───────────────────── цвета ───────────────────── */

const CATS = [
  { k: "near", t: "Почти токен", hint: "На вид как токен, но не он: разница глазом не видна или едва видна. Замените на ближайший токен." },
  { k: "alpha", t: "Другая прозрачность", hint: "Цвет совпадает с токеном, но прозрачность другая — обычно это подложки и затемнения. Возьмите токен нужной прозрачности или заведите его в систему." },
  { k: "off", t: "Мимо системы", hint: "Далеко от всех токенов. Решите: добавить такой цвет в дизайн-систему или заменить на существующий." },
  { k: "unbound", t: "Не привязаны", hint: "Цвет совпадает с токеном, но в части мест набран вручную. Привяжите эти места к токену." },
  { k: "rare", t: "Редкие", hint: "Цвет встречается один-два раза — чаще всего это опечатка." },
  { k: "all", t: "Все", hint: "Все цвета под текущими фильтрами, от самых частых." },
];
function inCat(i, k) {
  if (k === "near") return i.status === "near";
  if (k === "off") return i.status === "off";
  if (k === "alpha") return i.status === "alpha";
  if (k === "stray") return ["near", "alpha", "off"].includes(i.status);
  if (k === "unbound") return i.unbound;
  if (k === "rare") return i.rare && i.status !== "token";
  return true;
}
function swatch(c, a) { return `<span class="sw"><i style="background:#${c};opacity:${a / 100}"></i></span>`; }
function what(i) {
  if (i.status === "token") {
    const names = i.tokens.slice(0, 2).map(esc).join(", ") + (i.tokens.length > 2 ? ` и ещё ${i.tokens.length - 2}` : "");
    return i.unbound ? `<span class="tag unbound">не привязан</span>токен <b>${names}</b> · вручную ${fmt(i.raw)} из ${fmt(i.uses)}` : `<span class="tag token">токен</span><b>${names}</b>`;
  }
  if (i.status === "alpha" && i.nearest) {
    const n = i.nearest;
    return `<span class="tag alpha">другая прозрачность</span>цвет токена <b>${esc(n.name)}</b>, но ${i.alpha}% вместо ${n.alpha}%`;
  }
  if (i.status === "near" || i.status === "off") {
    const n = i.nearest;
    const tag = i.status === "near" ? '<span class="tag near">почти токен</span>' : '<span class="tag off">мимо системы</span>';
    if (!n) return tag;
    const alpha = n.dalpha ? `, прозрачность ${n.alpha}% вместо ${i.alpha}%` : "";
    const see = n.de < 1 ? "глазом не отличить" : n.de < 2 ? "едва заметно" : n.de < 5 ? "заметно при сравнении" : "другой цвет";
    return `${tag}ближе всего <b>${esc(n.name)}</b> ${esc(n.label)} — ${see}${alpha}`;
  }
  return '<span class="muted">справочник токенов не загружен</span>';
}

let colourState = { items: [], shown: 120 };
async function viewColours(el, params, stale) {
  renderFilters(true);
  const cat = params.get("cat") || "near";
  const data = await api("/api/colours" + fq());
  if (stale()) return;
  if (!data.tokens && ["near", "alpha", "off", "unbound", "stray"].includes(cat)) {
    el.innerHTML = `<div class="notice">Чтобы делить цвета на «почти токен», «мимо системы» и «не привязаны», нужен справочник токенов. <a href="#/settings">Загрузить справочник</a></div>`;
  } else el.innerHTML = "";
  const counts = Object.fromEntries(CATS.map((c) => [c.k, data.items.filter((i) => inCat(i, c.k)).length]));
  const cats = CATS.filter((c) => data.tokens || c.k === "rare" || c.k === "all");
  const active = cats.find((c) => c.k === cat) || (cat === "stray" ? { k: "stray", t: "Левые", hint: "Почти токен, другая прозрачность и мимо системы." } : cats[cats.length - 1]);
  colourState = { items: data.items.filter((i) => inCat(i, active.k)), shown: 120 };
  el.insertAdjacentHTML("beforeend", `
    <div class="cats">${cats.map((c) => `<button class="${c.k === active.k ? "on" : ""}" data-cat="${c.k}">${c.t}<em>${fmt(counts[c.k])}</em></button>`).join("")}</div>
    <p class="hint">${esc(active.hint)}</p>
    <div class="colours" id="clist"></div>`);
  el.querySelectorAll(".cats button").forEach((b) => (b.onclick = () => (location.hash = `#/colours?cat=${b.dataset.cat}`)));
  drawColours();
}
function drawColours() {
  const box = $("#clist");
  if (!box) return;
  const { items, shown } = colourState;
  if (!items.length) {
    box.innerHTML = `<div class="empty"><b>Здесь пусто</b><p>Под текущими фильтрами таких цветов нет.</p></div>`;
    return;
  }
  box.innerHTML = items.slice(0, shown).map((i, n) => `
    <div class="crow" data-n="${n}">
      ${swatch(i.color, i.alpha)}
      <div class="name">${esc(i.label)}<small>${esc(i.family)}${i.first_seen ? " · с " + esc(day(i.first_seen)) : ""}</small></div>
      <div class="num">${fmt(i.uses)} <span class="muted">${plural(i.uses, "раз", "раза", "раз")}</span></div>
      <div class="num c-screens">${fmt(i.screens)} <span class="muted">${plural(i.screens, "экран", "экрана", "экранов")}</span></div>
      <div class="num c-files">${fmt(i.files)} <span class="muted">${plural(i.files, "файл", "файла", "файлов")}</span></div>
      <div class="what">${what(i)}</div>
    </div>`).join("") + (items.length > shown ? `<button class="b quiet" id="more">Показать ещё ${fmt(Math.min(120, items.length - shown))} из ${fmt(items.length - shown)}</button>` : "");
  box.querySelectorAll(".crow").forEach((r) => (r.onclick = () => togglePlaces(r, items[+r.dataset.n])));
  const more = $("#more");
  if (more) more.onclick = () => { colourState.shown += 120; drawColours(); };
}
function layerRow(p) {
  const inside = p.exact_link ? "" : ' title="Слой внутри компонента: ссылка откроет сам инстанс"';
  const marks = (p.hidden ? ' <span class="muted">· скрыт</span>' : "") + (p.archived ? ' <span class="muted">· архив</span>' : "");
  const how = p.source === "v" ? "переменная" : p.source ? esc(p.source.slice(2)) : "вручную";
  const where = p.kind === "stop" ? "в градиенте" : p.slot === "stroke" ? "обводка" : "заливка";
  const sect = p.sections ? `<span class="label">${esc(p.sections)} ›</span> ` : "";
  return `<div class="place">${sect ? `<div class="path">${sect}` : '<div class="path">'}<code>${esc(p.name)}</code>
    <span class="when">${where} · ${how}${marks}</span></div>
    <a href="${esc(p.link)}" target="_blank" rel="noopener"${inside}>Открыть ↗</a></div>`;
}

async function toggleLayers(head, item, g) {
  const next = head.nextElementSibling;
  if (next && next.classList.contains("layers")) { next.remove(); head.classList.remove("open"); return; }
  head.classList.add("open");
  const box = document.createElement("div");
  box.className = "layers";
  box.innerHTML = '<div class="loading">Ищем слои…</div>';
  head.after(box);
  try {
    const d = await api("/api/places" + fq({ color: item.color, alpha: item.alpha, file_key: g.file_key, screen: g.screen_id || "" }));
    box.innerHTML = d.items.map(layerRow).join("") +
      (d.total > d.items.length ? `<div class="muted" style="padding:5px 0">и ещё ${fmt(d.total - d.items.length)}</div>` : "");
  } catch (e) { box.innerHTML = `<div class="error">${esc(e.message)}</div>`; }
}

async function togglePlaces(row, item, offset = 0) {
  const next = row.nextElementSibling;
  if (offset === 0 && next && next.classList.contains("places")) { next.remove(); row.classList.remove("open"); return; }
  row.classList.add("open");
  let box = offset ? next : null;
  if (!box) { box = document.createElement("div"); box.className = "places"; row.after(box); }
  if (!offset) box.innerHTML = '<div class="loading">Ищем места…</div>';
  try {
    const d = await api("/api/screens" + fq({ color: item.color, alpha: item.alpha, offset }));
    if (!offset) {
      box.innerHTML = `<div class="places-head">${fmt(d.total_places)} ${plural(d.total_places, "место", "места", "мест")} на ${fmt(d.total)} ${plural(d.total, "экране", "экранах", "экранах")}</div>`;
    } else {
      const m = box.querySelector(".more-places");
      if (m) m.remove();
    }
    const html = d.items.map((g, n) => {
      const layers = g.layers.map(esc).join(", ") + (g.more_layers ? ` и ещё ${g.more_layers}` : "");
      const marks = (g.hidden ? " · есть скрытые" : "") + (g.archived ? " · архив" : "");
      return `<div class="scr" data-n="${n}">
        <div class="path">${esc(g.file)}<span class="label">›</span>${esc(g.page)}<span class="label">›</span><b>${esc(g.screen)}</b></div>
        <div class="cnt">${fmt(g.count)} ${plural(g.count, "место", "места", "мест")} · ${layers}${marks}</div>
        <a href="${esc(g.link)}" target="_blank" rel="noopener">Экран ↗</a></div>`;
    }).join("");
    box.insertAdjacentHTML("beforeend", html);
    const heads = box.querySelectorAll(".scr");
    const groups = d.items;
    heads.forEach((h) => {
      if (h.dataset.bound) return;
      h.dataset.bound = "1";
      const g = groups[+h.dataset.n];
      if (!g) return;
      h.onclick = (e) => { if (e.target.closest("a")) return; e.stopPropagation(); toggleLayers(h, item, g); };
    });
    const left = d.total - (offset + d.items.length);
    if (left > 0) {
      box.insertAdjacentHTML("beforeend", `<button class="b quiet more-places">Ещё ${fmt(Math.min(d.limit, left))} ${plural(Math.min(d.limit, left), "экран", "экрана", "экранов")} из ${fmt(left)}</button>`);
      box.querySelector(".more-places").onclick = (e) => { e.stopPropagation(); togglePlaces(row, item, offset + d.items.length); };
    }
  } catch (e) { box.innerHTML = `<div class="error">${esc(e.message)}</div>`; }
}

/* ───────────────────── экраны → слои (общее для поиска и компонентов) ───────────────────── */

function layerLine(p) {
  const inside = p.exact_link ? "" : ' title="Слой внутри компонента: ссылка откроет сам инстанс"';
  const sect = p.sections ? `<span class="label">${esc(p.sections)} ›</span> ` : "";
  const what = p.type === "TEXT" && p.text ? `«${esc(p.text)}»` : esc(p.type.toLowerCase());
  const marks = [p.size, p.overridden ? "изменён" : "", p.hidden ? "скрыт" : ""].filter(Boolean).map(esc).join(" · ");
  return `<div class="place"><div class="path">${sect}<code>${esc(p.name)}</code>
    <span class="when">${what}${marks ? " · " + marks : ""}</span></div>
    <a href="${esc(p.link)}" target="_blank" rel="noopener"${inside}>Открыть ↗</a></div>`;
}

async function screensBlock(box, groupsUrl, layersUrl, emptyHint, offset = 0) {
  if (!offset) box.innerHTML = '<div class="loading">Ищем…</div>';
  let d;
  try { d = await api(groupsUrl(offset)); }
  catch (e) { box.innerHTML = `<div class="error">${esc(e.message)}</div>`; return; }
  if (!offset) {
    box.innerHTML = d.total
      ? `<div class="places-head">${fmt(d.total_places)} ${plural(d.total_places, "место", "места", "мест")} на ${fmt(d.total)} ${plural(d.total, "экране", "экранах", "экранах")}</div>`
      : `<div class="empty"><b>Ничего не нашлось</b><p>${emptyHint || "Попробуйте другой запрос или ослабьте фильтры."}</p></div>`;
  } else {
    const m = box.querySelector(".more-places");
    if (m) m.remove();
  }
  const start = box.querySelectorAll(".scr").length;
  box.insertAdjacentHTML("beforeend", d.items.map((g, n) => {
    const layers = g.layers.map(esc).join(", ") + (g.more_layers ? ` и ещё ${g.more_layers}` : "");
    return `<div class="scr" data-n="${start + n}">
      <div class="path">${esc(g.file)}<span class="label">›</span>${esc(g.page)}<span class="label">›</span><b>${esc(g.screen)}</b></div>
      <div class="cnt">${fmt(g.count)} ${plural(g.count, "место", "места", "мест")} · ${layers}</div>
      <a href="${esc(g.link)}" target="_blank" rel="noopener">Экран ↗</a></div>`;
  }).join(""));
  box._groups = (box._groups || []).slice(0, start).concat(d.items);
  box.querySelectorAll(".scr").forEach((h) => {
    if (h.dataset.bound) return;
    h.dataset.bound = "1";
    const g = box._groups[+h.dataset.n];
    h.onclick = async (e) => {
      if (e.target.closest("a")) return;
      const next = h.nextElementSibling;
      if (next && next.classList.contains("layers")) { next.remove(); h.classList.remove("open"); return; }
      h.classList.add("open");
      const lb = document.createElement("div");
      lb.className = "layers";
      lb.innerHTML = '<div class="loading">Ищем слои…</div>';
      h.after(lb);
      try {
        const r = await api(layersUrl(g));
        lb.innerHTML = r.items.map(layerLine).join("") + (r.total > r.items.length ? `<div class="muted" style="padding:5px 0">и ещё ${fmt(r.total - r.items.length)}</div>` : "");
      } catch (err) { lb.innerHTML = `<div class="error">${esc(err.message)}</div>`; }
    };
  });
  const left = d.total - (offset + d.items.length);
  if (left > 0) {
    box.insertAdjacentHTML("beforeend", `<button class="b quiet more-places">Ещё ${fmt(Math.min(d.limit, left))} из ${fmt(left)} ${plural(left, "экрана", "экранов", "экранов")}</button>`);
    box.querySelector(".more-places").onclick = () => screensBlock(box, groupsUrl, layersUrl, emptyHint, offset + d.items.length);
  }
}

/* ───────────────────── поиск ───────────────────── */

const MODES = [{ k: "text", t: "Текст и названия" }, { k: "size", t: "Размер" }, { k: "colour", t: "Цвет" }];

async function viewSearch(el, params) {
  renderFilters(true);
  const mode = MODES.some((m) => m.k === params.get("mode")) ? params.get("mode") : "text";
  const v = (k, d = "") => esc(params.get(k) || d);
  const forms = {
    text: `<input type="text" name="q" value="${v("q")}" placeholder="Слово или фраза — в любой форме и любом порядке" autofocus>
      <select name="where"><option value="both">в текстах и названиях слоёв</option><option value="text" ${params.get("where") === "text" ? "selected" : ""}>только в текстах</option><option value="name" ${params.get("where") === "name" ? "selected" : ""}>только в названиях</option></select>`,
    size: `<input type="text" name="w" value="${v("w")}" placeholder="Ширина" style="max-width:96px" inputmode="decimal">
      <span class="muted">×</span>
      <input type="text" name="h" value="${v("h")}" placeholder="Высота" style="max-width:96px" inputmode="decimal">
      <span class="muted">±</span>
      <input type="text" name="tol" value="${v("tol", "0")}" style="max-width:64px" inputmode="decimal" title="Допуск в пикселях">
      <select name="type"><option value="">любые слои</option><option value="instance" ${params.get("type") === "instance" ? "selected" : ""}>только инстансы</option><option value="frame" ${params.get("type") === "frame" ? "selected" : ""}>кадры и группы</option><option value="text" ${params.get("type") === "text" ? "selected" : ""}>тексты</option></select>`,
    colour: `<input type="color" id="pick" value="#${(params.get("hex") || "#FF006F").replace("#", "").slice(0, 6)}" style="width:40px;height:32px;padding:2px;border:none;background:none">
      <input type="text" name="hex" value="${v("hex", "#FF006F")}" placeholder="#RRGGBB" style="max-width:120px">
      <span class="label">похожие с разницей до</span>
      <input type="range" name="tol" min="0" max="10" step="0.5" value="${v("tol", "3")}" id="tolr" style="width:120px">
      <span id="tolv" class="label">${v("tol", "3")}</span>`,
  };
  el.innerHTML = `
    <div class="cats">${MODES.map((m) => `<button class="${m.k === mode ? "on" : ""}" data-mode="${m.k}">${m.t}</button>`).join("")}</div>
    <form class="row" id="sf" style="margin-bottom:14px">${forms[mode]}<button class="b main">Найти</button></form>
    <div id="sres"></div>`;
  el.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => (location.hash = `#/search?mode=${b.dataset.mode}`)));
  const f = $("#sf");
  if (mode === "colour") {
    const pick = $("#pick"), hex = f.elements.hex, tolr = $("#tolr");
    pick.oninput = () => (hex.value = pick.value.toUpperCase());
    hex.oninput = () => { if (/^#?[0-9a-f]{6}$/i.test(hex.value)) pick.value = "#" + hex.value.replace("#", ""); };
    tolr.oninput = () => ($("#tolv").textContent = tolr.value);
  }
  f.onsubmit = (e) => {
    e.preventDefault();
    const q = new URLSearchParams({ mode });
    for (const inp of f.elements) if (inp.name && inp.value) q.set(inp.name, inp.value.trim());
    location.hash = "#/search?" + q.toString();
  };
  const res = $("#sres");
  const p = Object.fromEntries(params);
  delete p.mode;
  if (mode === "text" && !p.q) { res.innerHTML = '<p class="hint">Найдёт «Купить 100 монет» по запросу «купите монеты»: слова — в любом порядке и любой форме. Ищет и по тексту, и по названию слоя.</p>'; return; }
  if (mode === "size" && !p.w && !p.h) { res.innerHTML = '<p class="hint">Например, 56 × 56 — все иконки и аватарки такого размера. Можно задать только ширину или только высоту.</p>'; return; }
  if (mode === "colour" && !params.get("hex")) { res.innerHTML = '<p class="hint">Найдёт цвет и похожие на него. Разница до 1 — глазом не отличить, до 3 — заметно только при сравнении.</p>'; return; }
  if (mode === "colour") {
    try {
      const d = await api("/api/search" + fq({ kind: "colour", hex: p.hex, tol: p.tol || 3 }));
      if (!d.items.length) { res.innerHTML = '<div class="empty"><b>Таких цветов нет</b><p>Увеличьте допуск или проверьте фильтры.</p></div>'; return; }
      res.innerHTML = `<div class="places-head">${fmt(d.items.length)} ${plural(d.items.length, "цвет", "цвета", "цветов")} — от самого близкого</div><div class="colours" id="clist"></div>`;
      colourState = { items: d.items.map((i) => ({ ...i, family: `разница ${String(i.de).replace(".", ",")} · ${i.family}` })), shown: 120 };
      drawColours();
    } catch (e) { res.innerHTML = `<div class="error">${esc(e.message)}</div>`; }
    return;
  }
  const base = { kind: mode, ...p };
  screensBlock(res,
    (offset) => "/api/search" + fq({ ...base, offset }),
    (g) => "/api/search" + fq({ ...base, file_key: g.file_key, screen: g.screen_id || "" }),
    mode === "text" ? "Проверьте написание или поищите по одному слову." : "Увеличьте допуск или уберите ограничение по типу слоя.");
}

/* ───────────────────── типографика ───────────────────── */

const TCATS = [
  { k: "unbound", t: "Не привязаны", hint: "Шрифт, кегль и интерлиньяж точно как у стиля системы, но стиль не назначен. Назначьте стиль — внешне ничего не изменится." },
  { k: "near", t: "Почти стиль", hint: "Тот же шрифт и вес, но кегль или интерлиньяж чуть другие — часто это масштабированный текст. Замените на стиль." },
  { k: "off", t: "Мимо системы", hint: "Такого сочетания в системе нет: другой шрифт, вес или размер. Решите, нужен ли новый стиль, или замените на существующий." },
  { k: "all", t: "Все", hint: "Все сочетания шрифта у текстов без стиля." },
];

function fontSample(f) {
  const size = Math.max(11, Math.min(f.size || 14, 26));
  return `<span class="fsample" style="font-family:'${esc(f.family).replace(/'/g, "")}',sans-serif;font-weight:${f.weight || 400};font-size:${size}px">Аа</span>`;
}
function fontWhat(i) {
  if (i.status === "unbound") return `<span class="tag unbound">не привязан</span>как стиль <b>${i.styles.map(esc).join(", ")}</b>`;
  const n = i.nearest;
  if (!n) return i.family_known
    ? `<span class="tag off">мимо системы</span>шрифт ${esc(i.font.family)} в системе есть, но не в этом начертании`
    : `<span class="tag off">мимо системы</span>шрифта ${esc(i.font.family)} в системе нет вовсе`;
  const diff = [n.dsize ? `кегль ${n.dsize > 0 ? "+" : ""}${String(n.dsize).replace(".", ",")}` : "", n.dline ? `интерлиньяж ${n.dline > 0 ? "+" : ""}${String(n.dline).replace(".", ",")}` : ""].filter(Boolean).join(", ");
  return `${i.status === "near" ? '<span class="tag near">почти стиль</span>' : '<span class="tag off">мимо системы</span>'}ближе всего <b>${esc(n.name)}</b> ${esc(n.label)}${diff ? " — " + diff : ""}`;
}

async function viewTypography(el, params, stale) {
  renderFilters(true);
  const cat = params.get("cat") || "unbound";
  const d = await api("/api/typography" + fq());
  if (stale()) return;
  const counts = Object.fromEntries(TCATS.map((c) => [c.k, d.items.filter((i) => c.k === "all" || i.status === c.k).reduce((n, i) => n + i.uses, 0)]));
  const active = TCATS.find((c) => c.k === cat) || TCATS[0];
  const items = d.items.filter((i) => active.k === "all" || i.status === active.k);
  const loose = d.items.reduce((n, i) => n + i.uses, 0);
  el.innerHTML = `
    <p class="sub" style="margin-top:0">Система выведена из самих макетов: ${fmt(d.styles.length)} ${plural(d.styles.length, "стиль", "стиля", "стилей")} по текстам, где стиль назначен. С ней сравниваются ${fmt(loose)} ${plural(loose, "текст", "текста", "текстов")} без стиля — только положенные на экран вручную: внутри компонентов типографику задаёт библиотека.</p>
    <div class="cats">${TCATS.map((c) => `<button class="${c.k === active.k ? "on" : ""}" data-cat="${c.k}">${c.t}<em>${fmt(counts[c.k])}</em></button>`).join("")}</div>
    <p class="hint">${esc(active.hint)}</p>
    <div id="flist">${items.length ? "" : '<div class="empty"><b>Здесь пусто</b><p>Под текущими фильтрами таких текстов нет.</p></div>'}</div>
    <h2>Стили системы</h2>
    <p class="sub">Как они на самом деле используются: самое частое сочетание шрифта у каждого стиля.</p>
    <div class="styles">${d.styles.map((s) => `<div class="srow">${fontSample(s.font)}<div class="name">${esc(s.name)}<small>${esc(s.label)}</small></div><div class="num">${fmt(s.uses)} <span class="muted">${plural(s.uses, "текст", "текста", "текстов")}</span></div></div>`).join("")}</div>`;
  el.querySelectorAll("[data-cat]").forEach((b) => (b.onclick = () => (location.hash = `#/typography?cat=${b.dataset.cat}`)));
  $("#flist").insertAdjacentHTML("beforeend", items.map((i, n) => `
    <div class="crow frow" data-n="${n}">${fontSample(i.font)}
      <div class="name">${esc(i.label)}<small>${esc(i.font.family)}${i.first_seen ? " · с " + esc(day(i.first_seen)) : ""}</small></div>
      <div class="num">${fmt(i.uses)} <span class="muted">${plural(i.uses, "текст", "текста", "текстов")}</span></div>
      <div class="num c-screens">${fmt(i.screens)} <span class="muted">${plural(i.screens, "экран", "экрана", "экранов")}</span></div>
      <div class="num c-files">${fmt(i.files)} <span class="muted">${plural(i.files, "файл", "файла", "файлов")}</span></div>
      <div class="what">${fontWhat(i)}</div></div>`).join(""));
  el.querySelectorAll(".frow").forEach((r) => (r.onclick = () => {
    const next = r.nextElementSibling;
    if (next && next.classList.contains("places")) { next.remove(); r.classList.remove("open"); return; }
    r.classList.add("open");
    const box = document.createElement("div");
    box.className = "places";
    r.after(box);
    const base = { kind: "font", font: items[+r.dataset.n].font_id };
    screensBlock(box, (offset) => "/api/search" + fq({ ...base, offset }), (g) => "/api/search" + fq({ ...base, file_key: g.file_key, screen: g.screen_id || "" }));
  }));
}

/* ───────────────────── отступы, скругления, обводки ───────────────────── */

const SGROUPS = [
  { k: "spacing", t: "Отступы", unit: "отступ", what: "отступов и промежутков auto layout" },
  { k: "radius", t: "Скругления", unit: "скругление", what: "скруглений углов" },
  { k: "stroke", t: "Обводки", unit: "обводка", what: "толщин обводки" },
];
const KIND_NAMES = { gap: "промежуток", padding: "поле", radius: "угол", stroke: "обводка" };
const num = (v) => String(v).replace(".", ",");

function scaleCats(source) {
  return [
    { k: "near", t: "Почти шкала", hint: "До значения шкалы не больше пикселя — обычно след масштабирования или ручного набора. Поправьте на значение шкалы." },
    { k: "off", t: "Мимо шкалы", hint: "Такого значения в шкале нет. Решите, нужно ли оно, или замените на ближайшее." },
    source === "variables"
      ? { k: "unbound", t: "Не привязаны", hint: "Значение есть в шкале, но набрано числом, без переменной. Привяжите переменную — внешне ничего не изменится." }
      : { k: "ok", t: "На сетке", hint: "Значение ложится на привычную сетку. Переменных для этих чисел в макетах нет, так что привязывать не к чему." },
    { k: "all", t: "Все", hint: "Все значения, набранные вручную." },
  ];
}

function scaleSample(group, v) {
  const x = Math.min(v, 28);
  if (group === "radius") return `<span class="psample"><i style="width:22px;height:22px;border:1.5px solid var(--txt);border-radius:${Math.min(v, 11)}px"></i></span>`;
  if (group === "stroke") return `<span class="psample"><i style="width:22px;height:${Math.min(v, 8)}px;background:var(--txt);border-radius:1px"></i></span>`;
  return `<span class="psample"><i style="width:${Math.max(2, x)}px;height:14px;background:var(--fair-tx);opacity:.55;border-radius:1px"></i></span>`;
}

function scaleWhat(i, unit) {
  if (i.status === "unbound") return '<span class="tag unbound">не привязано</span>значение шкалы, набрано числом';
  if (i.status === "ok") return '<span class="tag token">на сетке</span>';
  const tag = i.status === "near" ? '<span class="tag near">почти шкала</span>' : '<span class="tag off">мимо шкалы</span>';
  return `${tag}ближе всего <b>${num(i.nearest)}</b>`;
}

async function viewSpacing(el, params, stale) {
  renderFilters(true);
  const group = SGROUPS.find((g) => g.k === params.get("g")) || SGROUPS[0];
  const all = await api("/api/scales" + fq());
  if (stale()) return;
  const d = all[group.k];
  const cats = scaleCats(d.source);
  const active = cats.find((c) => c.k === params.get("cat")) || cats[0];
  const counts = Object.fromEntries(cats.map((c) => [c.k, d.items.filter((i) => c.k === "all" || i.status === c.k).reduce((n, i) => n + i.uses, 0)]));
  const items = d.items.filter((i) => active.k === "all" || i.status === active.k);
  const t = d.totals;
  const manual = t.ok + t.unbound + t.near + t.off;
  const scaleLine = d.source === "variables"
    ? `Шкала — из переменных, которые уже привязаны в макетах: ${d.scale.map((s) => `<code>${num(s.value)}</code>`).join(" ")}`
    : group.k === "spacing" ? "Переменных для отступов в макетах нет — сравниваем с привычной сеткой: кратно 4 (и 2)."
    : group.k === "radius" ? "Переменных для скруглений в макетах нет — сравниваем с сеткой: чётные значения."
    : "Переменных для обводок в макетах нет — принятыми считаются 0,5 · 1 · 1,5 · 2 · 3 · 4.";
  el.innerHTML = `
    <div class="cats">${SGROUPS.map((g) => `<button class="${g.k === group.k ? "on" : ""}" data-g="${g.k}">${g.t}</button>`).join("")}</div>
    <p class="sub" style="margin-top:0">${scaleLine}<br>
      Через переменную — ${fmt(t.bound)}, вручную — ${fmt(manual)}${t.pill ? `, ещё ${fmt(t.pill)} ${plural(t.pill, "«таблетка»", "«таблетки»", "«таблеток»")} — скругление в половину стороны, его число неважно` : ""}. Только слои, положенные на экран вручную: внутри компонентов эти числа задаёт библиотека.</p>
    <div class="cats">${cats.map((c) => `<button class="${c.k === active.k ? "on" : ""}" data-cat="${c.k}">${c.t}<em>${fmt(counts[c.k])}</em></button>`).join("")}</div>
    <p class="hint">${esc(active.hint)}</p>
    <div id="plist">${items.length ? "" : '<div class="empty"><b>Здесь пусто</b><p>Под текущими фильтрами таких значений нет.</p></div>'}</div>`;
  el.querySelectorAll("[data-g]").forEach((b) => (b.onclick = () => (location.hash = `#/spacing?g=${b.dataset.g}`)));
  el.querySelectorAll("[data-cat]").forEach((b) => (b.onclick = () => (location.hash = `#/spacing?g=${group.k}&cat=${b.dataset.cat}`)));
  $("#plist").insertAdjacentHTML("beforeend", items.map((i, n) => {
    const kinds = Object.entries(i.kinds).map(([k, c]) => `${KIND_NAMES[k] || k} ${fmt(c)}`).join(" · ");
    return `<div class="crow prow" data-n="${n}">${scaleSample(group.k, i.value)}
      <div class="name">${num(i.value)} px<small>${esc(kinds)}${i.first_seen ? " · с " + esc(day(i.first_seen)) : ""}</small></div>
      <div class="num">${fmt(i.uses)} <span class="muted">${plural(i.uses, "раз", "раза", "раз")}</span></div>
      <div class="num c-screens">${fmt(i.screens)} <span class="muted">${plural(i.screens, "экран", "экрана", "экранов")}</span></div>
      <div class="num c-files">${fmt(i.files)} <span class="muted">${plural(i.files, "файл", "файла", "файлов")}</span></div>
      <div class="what">${scaleWhat(i, group.unit)}</div></div>`;
  }).join(""));
  el.querySelectorAll(".prow").forEach((r) => (r.onclick = () => {
    const next = r.nextElementSibling;
    if (next && next.classList.contains("places")) { next.remove(); r.classList.remove("open"); return; }
    r.classList.add("open");
    const box = document.createElement("div");
    box.className = "places";
    r.after(box);
    const base = { kind: "prop", group: group.k, value: items[+r.dataset.n].value };
    screensBlock(box, (offset) => "/api/search" + fq({ ...base, offset }), (g) => "/api/search" + fq({ ...base, file_key: g.file_key, screen: g.screen_id || "" }));
  }));
}

/* ───────────────────── эффекты ───────────────────── */

const ECATS = [
  { k: "unbound", t: "Не привязаны", hint: "Параметры точно как в стиле эффекта, но стиль не назначен. Назначьте стиль — внешне ничего не изменится." },
  { k: "near", t: "Почти стиль", hint: "Тот же вид и цвет, смещение или размытие отличаются на пиксель-два. Замените на стиль." },
  { k: "off", t: "Мимо системы", hint: "Такого эффекта в стилях нет. Решите, нужен ли новый стиль, или замените на существующий." },
  { k: "all", t: "Все", hint: "Все эффекты, набранные вручную." },
];

function effectSample(e) {
  const c = e.color ? `rgba(${parseInt(e.color.slice(0, 2), 16)},${parseInt(e.color.slice(2, 4), 16)},${parseInt(e.color.slice(4, 6), 16)},${(e.alpha ?? 100) / 100})` : "rgba(0,0,0,.25)";
  let style;
  if (e.type === "DROP_SHADOW") style = `box-shadow:${e.x || 0}px ${e.y || 0}px ${e.radius || 0}px ${e.spread || 0}px ${c}`;
  else if (e.type === "INNER_SHADOW") style = `box-shadow:inset ${e.x || 0}px ${e.y || 0}px ${e.radius || 0}px ${e.spread || 0}px ${c}`;
  else style = `filter:blur(${Math.min((e.radius || 0) / 4, 4)}px);background:var(--label)`;
  return `<span class="esample"><i style="${style}"></i></span>`;
}
function effectColour(e) {
  return e.color ? `<code>#${esc(e.color)}</code>${e.alpha != null && e.alpha < 100 ? " " + e.alpha + "%" : ""}` : "";
}
const joinDot = (...parts) => parts.filter(Boolean).join(" · ");
function effectWhat(i) {
  if (i.status === "unbound") return `<span class="tag unbound">не привязан</span>как стиль <b>${i.styles.map(esc).join(", ")}</b>`;
  if (i.status === "near") return `<span class="tag near">почти стиль</span><b>${i.styles.map(esc).join(", ")}</b> — ${esc(i.nearest)}`;
  return '<span class="tag off">мимо системы</span>';
}

async function viewEffects(el, params, stale) {
  renderFilters(true);
  const d = await api("/api/effects" + fq());
  if (stale()) return;
  const active = ECATS.find((c) => c.k === params.get("cat")) || ECATS[0];
  const counts = Object.fromEntries(ECATS.map((c) => [c.k, d.items.filter((i) => c.k === "all" || i.status === c.k).reduce((n, i) => n + i.uses, 0)]));
  const items = d.items.filter((i) => active.k === "all" || i.status === active.k);
  const manual = d.items.reduce((n, i) => n + i.uses, 0);
  el.innerHTML = `
    <p class="sub" style="margin-top:0">Тени и размытия. Со стилем — ${fmt(d.totals.styled)}, вручную — ${fmt(manual)}. Система выведена из самих макетов: ${fmt(d.styles.length)} ${plural(d.styles.length, "эффект", "эффекта", "эффектов")} из стилей. Только слои, положенные на экран вручную.</p>
    <div class="cats">${ECATS.map((c) => `<button class="${c.k === active.k ? "on" : ""}" data-cat="${c.k}">${c.t}<em>${fmt(counts[c.k])}</em></button>`).join("")}</div>
    <p class="hint">${esc(active.hint)}</p>
    <div id="elist">${items.length ? "" : '<div class="empty"><b>Здесь пусто</b><p>Под текущими фильтрами таких эффектов нет.</p></div>'}</div>
    ${d.styles.length ? `<h2>Эффекты из стилей</h2>
    <div class="styles">${d.styles.map((s) => `<div class="srow">${effectSample(s)}<div class="name">${esc(s.styles.join(", "))}<small>${joinDot(esc(s.label), effectColour(s))}</small></div><div class="num">${fmt(s.uses)}</div></div>`).join("")}</div>` : ""}`;
  el.querySelectorAll("[data-cat]").forEach((b) => (b.onclick = () => (location.hash = `#/effects?cat=${b.dataset.cat}`)));
  $("#elist").insertAdjacentHTML("beforeend", items.map((i, n) => `
    <div class="crow erow" data-n="${n}">${effectSample(i)}
      <div class="name">${esc(i.label)}<small>${joinDot(effectColour(i), i.first_seen ? "с " + esc(day(i.first_seen)) : "")}</small></div>
      <div class="num">${fmt(i.uses)} <span class="muted">${plural(i.uses, "слой", "слоя", "слоёв")}</span></div>
      <div class="num c-screens">${fmt(i.screens)} <span class="muted">${plural(i.screens, "экран", "экрана", "экранов")}</span></div>
      <div class="num c-files">${fmt(i.files)} <span class="muted">${plural(i.files, "файл", "файла", "файлов")}</span></div>
      <div class="what">${effectWhat(i)}</div></div>`).join(""));
  el.querySelectorAll(".erow").forEach((r) => (r.onclick = () => {
    const next = r.nextElementSibling;
    if (next && next.classList.contains("places")) { next.remove(); r.classList.remove("open"); return; }
    r.classList.add("open");
    const box = document.createElement("div");
    box.className = "places";
    r.after(box);
    const i = items[+r.dataset.n];
    const base = { kind: "effect", type: i.type, color: i.color ?? "", alpha: i.alpha ?? "", x: i.x ?? "", y: i.y ?? "", radius: i.radius ?? "", spread: i.spread ?? "" };
    screensBlock(box, (offset) => "/api/search" + fq({ ...base, offset }), (g) => "/api/search" + fq({ ...base, file_key: g.file_key, screen: g.screen_id || "" }));
  }));
}

/* ───────────────────── картинки ───────────────────── */

const MODE_NAMES = { FILL: "заполнить", FIT: "вписать", CROP: "обрезать", TILE: "плиткой", STRETCH: "растянуть" };

async function viewImages(el, params, stale) {
  renderFilters(true);
  const d = await api("/api/images" + fq());
  if (stale()) return;
  if (!d.total) {
    el.innerHTML = '<div class="empty"><b>Картинок нет</b><p>Под текущими фильтрами ни у одного слоя нет картинки в заливке.</p></div>';
    return;
  }
  el.innerHTML = `
    <p class="sub" style="margin-top:0">${fmt(d.total)} ${plural(d.total, "картинка", "картинки", "картинок")} в ${fmt(d.total_uses)} ${plural(d.total_uses, "месте", "местах", "местах")}; ${fmt(d.once)} стоят по одному разу. Одна и та же картинка в разных местах — одна строка: так видны и повторы, и забытые заглушки.</p>
    <div id="ilist">${d.items.map((i, n) => `
      <div class="crow irow" data-n="${n}"><span class="thumb" data-ref="${esc(i.ref)}" data-file="${esc(i.file_key)}"></span>
        <div class="name">${esc(i.name)}<small>${i.modes.map((m) => MODE_NAMES[m] || m.toLowerCase()).join(", ")} · до ${fmt(i.max_w)} × ${fmt(i.max_h)}${i.first_seen ? " · с " + esc(day(i.first_seen)) : ""}</small></div>
        <div class="num">${fmt(i.uses)} <span class="muted">${plural(i.uses, "место", "места", "мест")}</span></div>
        <div class="num c-screens">${fmt(i.screens)} <span class="muted">${plural(i.screens, "экран", "экрана", "экранов")}</span></div>
        <div class="num c-files">${fmt(i.files)} <span class="muted">${plural(i.files, "файл", "файла", "файлов")}</span></div>
        <div class="what">${i.uses > 1 ? `<span class="tag near">повтор</span>одна картинка в ${fmt(i.uses)} ${plural(i.uses, "месте", "местах", "местах")}` : ""}</div></div>`).join("")}</div>
    ${d.total > d.items.length ? `<p class="muted">Показаны ${fmt(d.items.length)} самых частых из ${fmt(d.total)}.</p>` : ""}`;
  el.querySelectorAll(".irow").forEach((r) => (r.onclick = () => {
    const next = r.nextElementSibling;
    if (next && next.classList.contains("places")) { next.remove(); r.classList.remove("open"); return; }
    r.classList.add("open");
    const box = document.createElement("div");
    box.className = "places";
    r.after(box);
    const base = { kind: "image", ref: d.items[+r.dataset.n].ref };
    screensBlock(box, (offset) => "/api/search" + fq({ ...base, offset }), (g) => "/api/search" + fq({ ...base, file_key: g.file_key, screen: g.screen_id || "" }));
  }));
  // Превью — адреса картинок Figma отдаёт по файлу; просим по разу на файл.
  const byFile = {};
  el.querySelectorAll(".thumb").forEach((t) => (byFile[t.dataset.file] = byFile[t.dataset.file] || []).push(t));
  for (const [fk, thumbs] of Object.entries(byFile)) {
    api("/api/image-urls?file_key=" + encodeURIComponent(fk)).then((r) => {
      if (stale()) return;
      thumbs.forEach((t) => {
        const url = r.urls[t.dataset.ref];
        if (url) t.innerHTML = `<img src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`;
      });
    }).catch(() => { /* превью — не главное: без него список всё равно полезен */ });
  }
}

/* ───────────────────── компоненты ───────────────────── */

async function viewComponents(el, params, stale) {
  renderFilters(true);
  const q = params.get("q") || "";
  const [c, det] = await Promise.all([api("/api/components" + fq({ q })), api("/api/detached" + fq())]);
  if (stale()) return;
  const inst = c.items.reduce((n, g) => n + g.instances, 0);
  el.innerHTML = `
    <form class="row" id="cf" style="margin-bottom:14px"><input type="text" name="q" value="${esc(q)}" placeholder="Название компонента или набора"><button class="b main">Найти</button></form>
    <h2>Компоненты в макетах</h2>
    <p class="sub">${fmt(c.total)} ${plural(c.total, "набор или компонент", "набора или компонента", "наборов и компонентов")} · ${fmt(inst)} ${plural(inst, "инстанс", "инстанса", "инстансов")}. Нажмите, чтобы увидеть варианты и где они стоят.</p>
    <div id="klist">${c.items.length ? "" : '<div class="empty"><b>Ничего не нашлось</b><p>Под текущими фильтрами инстансов таких компонентов нет.</p></div>'}</div>
    <h2>Похоже на отвязанные копии${det.total ? ` <span class="muted">${det.capped ? fmt(det.total) + " и больше" : fmt(det.total)}</span>` : ""}</h2>
    <p class="sub">Кадры и группы, названные как компонент файла, но не являющиеся инстансом. Когда инстанс отвязывают, кадр сохраняет имя компонента. Это подсказка, а не приговор: так же может называться и обычный кадр.</p>
    <div id="dlist">${det.items.length ? det.items.map((d) => `<div class="place"><div class="path">${esc(d.file)}<span class="label">›</span>${esc(d.page)}<span class="label">›</span>${esc(d.screen)}<span class="label">›</span><code>${esc(d.name)}</code></div><a href="${esc(d.link)}" target="_blank" rel="noopener">Открыть ↗</a></div>`).join("") : '<p class="muted">Не нашлось.</p>'}</div>`;
  $("#cf").onsubmit = (e) => { e.preventDefault(); const v = e.target.elements.q.value.trim(); location.hash = "#/components" + (v ? "?q=" + encodeURIComponent(v) : ""); };
  $("#klist").insertAdjacentHTML("beforeend", c.items.map((g, n) => `
    <div class="krow" data-n="${n}">
      <div class="name">${esc(g.title)} <span class="tag ${g.remote ? "token" : "near"}">${g.remote ? "библиотека" : "свой"}</span>
        <small>${Object.keys(g.variants).length ? Object.entries(g.variants).map(([k, vs]) => `${esc(k)}: ${Object.keys(vs).length}`).join(" · ") : "без вариантов"}</small></div>
      <div class="num">${fmt(g.instances)} <span class="muted">${plural(g.instances, "инстанс", "инстанса", "инстансов")}</span></div>
      <div class="num c-screens">${fmt(g.screens)} <span class="muted">${plural(g.screens, "экран", "экрана", "экранов")}</span></div>
      <div class="num c-files">${fmt(g.files)} <span class="muted">${plural(g.files, "файл", "файла", "файлов")}</span></div>
      <div class="num">${g.overridden ? `${pct(g.overridden * 100 / g.instances)} <span class="muted">изменено</span>` : '<span class="muted">не менялся</span>'}</div>
    </div>`).join(""));
  el.querySelectorAll(".krow").forEach((r) => (r.onclick = () => openComponent(r, c.items[+r.dataset.n])));
}

function openComponent(row, g, variant = "") {
  let box = row.nextElementSibling;
  if (!variant && box && box.classList.contains("kbox")) { box.remove(); row.classList.remove("open"); return; }
  row.classList.add("open");
  if (!box || !box.classList.contains("kbox")) { box = document.createElement("div"); box.className = "kbox places"; row.after(box); }
  const facets = Object.entries(g.variants).map(([k, vs]) => `<div class="facet"><span class="label">${esc(k)}</span>
    ${Object.entries(vs).sort((a, b) => b[1] - a[1]).map(([val, n]) => {
      const key = `${k}=${val}`;
      return `<button class="chip ${variant === key ? "on" : ""}" data-v="${esc(key)}">${esc(val)} <span class="muted">${fmt(n)}</span></button>`;
    }).join("")}</div>`).join("");
  box.innerHTML = `${facets ? `<div class="facets">${facets}</div>` : ""}<div class="kres"></div>`;
  box.querySelectorAll("[data-v]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); openComponent(row, g, variant === b.dataset.v ? "" : b.dataset.v); }));
  const base = { kind: "component", ...(g.set ? { set: g.set } : { cname: g.cname }), ...(variant ? { variant } : {}) };
  screensBlock(box.querySelector(".kres"),
    (offset) => "/api/search" + fq({ ...base, offset }),
    (gr) => "/api/search" + fq({ ...base, file_key: gr.file_key, screen: gr.screen_id || "" }));
}

/* ───────────────────── источники ───────────────────── */

async function viewSources(el, params, stale) {
  renderFilters(false);
  const st = await api("/api/state");
  if (stale()) return;
  const running = st.job && st.job.running;
  el.innerHTML = `
    <h2>Файлы Figma</h2>
    <p class="sub">Вставьте ссылку на файл. coloro загрузит его целиком, а что учитывать — выберете фильтрами.</p>
    <div class="row" style="margin-bottom:6px">
      <input type="url" id="url" placeholder="https://www.figma.com/design/…" autocomplete="off">
      <input type="text" id="pages" placeholder="Только страницы (необязательно)" style="max-width:240px" title="Для очень больших файлов: загружать только страницы с такими словами, через запятую">
      <button class="b main" id="add">Добавить</button>
    </div>
    <div class="row" style="margin:14px 0 10px">
      <button class="b" id="upd" ${running || !st.sources.length ? "disabled" : ""}>Обновить всё</button>
      <span class="muted">Качаются только изменившиеся файлы — проверка версии занимает секунду.</span>
    </div>
    <div id="slist">${st.sources.length ? "" : '<div class="empty"><b>Пока ни одного файла</b><p>Добавьте ссылку выше.</p></div>'}</div>`;
  if (!st.figma_token) el.insertAdjacentHTML("afterbegin", `<div class="notice">Чтобы загружать файлы, задайте токен Figma. <a href="#/settings">Открыть настройки</a></div>`);
  const cur = (st.job && st.job.current) || {};
  $("#slist").insertAdjacentHTML("beforeend", st.sources.map((s) => {
    const f = s.file;
    const name = f ? esc(f.name) : `<span class="muted">${esc(s.url)}</span>`;
    const pages = f ? f.pages.map((p) => `<span class="pg ${p.status === "failed" ? "failed" : ""} ${p.archived ? "archived" : ""}" title="${esc(p.status === "failed" ? "Не загрузилась: " + (p.error || "") : p.archived ? "Архивная страница — по умолчанию не учитывается" : fmt(p.nodes) + " слоёв")}">${esc(p.name)}</span>`).join("") : "";
    const c = f && cur[f.name];
    const prog = c ? `<div class="bar"><i style="width:${Math.round((c.index - 1) / c.total * 100)}%"></i></div><div class="meta">${esc(c.page)} · ${c.index} из ${c.total}</div>` : "";
    const meta = f ? `изменён в Figma ${esc(day(f.last_modified))} · загружен ${esc(ago(f.loaded_at)) || "ещё не до конца"}${s.pages ? " · только страницы: " + esc(s.pages.join(", ")) : ""}${f.outdated_format ? " · нужна перезагрузка в новом формате" : ""}`
      : "ещё не загружен";
    return `<div class="src"><div class="top"><b>${name}</b><span class="grow"></span>
      <button class="b quiet" data-upd="${esc(s.file_key)}" ${running ? "disabled" : ""}>Обновить</button>
      <button class="b quiet" data-del="${s.id}">Удалить</button></div>
      <div class="meta">${meta}</div>${prog}<div class="pages">${pages}</div></div>`;
  }).join(""));
  $("#add").onclick = async () => {
    const url = $("#url").value.trim();
    if (!url) { toast("Вставьте ссылку на файл Figma"); return; }
    try {
      await api("/api/sources", { url, pages: $("#pages").value.split(",").map((x) => x.trim()).filter(Boolean) });
      toast("Ссылка добавлена");
      route();
      if (st.figma_token) startUpdate();
    } catch (e) { toast(e.message); }
  };
  $("#url").onkeydown = (e) => { if (e.key === "Enter") $("#add").click(); };
  const upd = $("#upd");
  if (upd) upd.onclick = () => startUpdate();
  el.querySelectorAll("[data-upd]").forEach((b) => (b.onclick = () => startUpdate({ file_key: b.dataset.upd })));
  el.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Удалить ссылку? Данные файла уйдут из базы, если на него не ведёт другая ссылка.")) return;
    await api("/api/sources/remove", { id: +b.dataset.del });
    route();
  }));
}

/* ───────────────────── настройки ───────────────────── */

async function viewSettings(el, params, stale) {
  renderFilters(false);
  const st = await api("/api/state");
  if (stale()) return;
  const t = st.tokens;
  el.innerHTML = `
    <h2>Токен Figma</h2>
    <p class="sub">${st.figma_token ? "Задан. Хранится только на этом компьютере, в файле, который может прочитать только ваша учётная запись." : "Не задан. Без него coloro не сможет загрузить файлы."}
      Получить: Figma → настройки аккаунта → Security → Personal access tokens, право на чтение файлов.</p>
    <div class="row"><input type="password" id="tok" placeholder="${st.figma_token ? "Вставьте новый, чтобы заменить" : "figd_…"}" autocomplete="off" style="max-width:420px">
      <button class="b main" id="saveTok">Сохранить</button></div>

    <h2>Справочник токенов дизайн-системы</h2>
    <p class="sub">${t.count ? `Загружен «${esc(t.file)}» — ${fmt(t.count)} ${plural(t.count, "токен", "токена", "токенов")}, ${esc(ago(t.loaded_at))}.` : "Не загружен. По нему coloro понимает, какие цвета мимо системы, а какие почти совпадают с токеном."}
      Подойдёт W3C Design Tokens, Tokens Studio, выгрузка переменных или CSV с колонками «имя» и «значение».</p>
    <div class="row"><input type="file" id="tfile" accept=".json,.csv,.txt,application/json,text/csv"><button class="b main" id="upTok">Загрузить</button></div>`;
  $("#saveTok").onclick = async () => {
    const v = $("#tok").value.trim();
    if (!v) { toast("Вставьте токен"); return; }
    try { await api("/api/figma-token", { token: v }); $("#tok").value = ""; toast("Токен сохранён"); route(); }
    catch (e) { toast(e.message); }
  };
  $("#upTok").onclick = async () => {
    const f = $("#tfile").files[0];
    if (!f) { toast("Выберите файл справочника"); return; }
    try {
      const r = await api("/api/tokens", { filename: f.name, text: await f.text() });
      toast(`Загружено ${fmt(r.names)} ${plural(r.names, "токен", "токена", "токенов")}`);
      route();
    } catch (e) { toast(e.message); }
  };
}

/* ───────────────────── маршруты ───────────────────── */

const VIEWS = { "": viewOverview, colours: viewColours, search: viewSearch, typography: viewTypography, spacing: viewSpacing, effects: viewEffects, images: viewImages, components: viewComponents, sources: viewSources, settings: viewSettings };
// Номер текущего перехода. Медленный ответ предыдущего экрана не должен затереть уже
// открытый следующий: общая картина считается дольше, чем открываются цвета.
let routeSeq = 0;
async function route() {
  const seq = ++routeSeq;
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const name = VIEWS[path] ? path : "";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.v === (name || "overview")));
  const el = $("#view");
  // Сразу показываем, что экран сменился: иначе медленный экран выглядит как несработавший клик.
  if (el.dataset.view !== (name || "overview")) el.innerHTML = '<div class="loading">Загрузка…</div>';
  el.dataset.view = name || "overview";
  try { await VIEWS[name](el, new URLSearchParams(query || ""), () => seq !== routeSeq); }
  catch (e) { if (seq === routeSeq) el.innerHTML = `<div class="error">Не получилось загрузить данные: ${esc(e.message)}</div>`; }
}

function applyTheme(light) {
  document.body.classList.toggle("light", light);
  document.documentElement.classList.remove("pre-light");
  try { localStorage.setItem("coloro.theme", light ? "light" : "dark"); } catch (e) { /* не страшно */ }
}
$("#theme").onclick = () => applyTheme(!document.body.classList.contains("light"));
applyTheme(document.documentElement.classList.contains("pre-light"));

window.addEventListener("hashchange", route);
route();
pollJob();
