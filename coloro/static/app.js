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
  { key: "text_nostyle_pct", title: "Тексты без стиля", hint: "Доля текстов без текстового стиля — только тех, что положены на экран вручную: внутри компонентов стиль задаёт библиотека", pct: true },
  { key: "generic", title: "Безымянные", hint: "Кадры и группы с названием по умолчанию — Frame 12, Group 7 — только положенные на экран вручную: внутри компонентов названия задаёт библиотека" },
];

async function viewOverview(el, params, stale) {
  renderFilters(true);
  const [st, o] = await Promise.all([api("/api/state"), api("/api/overview" + fq())]);
  if (stale()) return;
  o.files.forEach((f) => (fileNames[f.file_key] = f.name));
  if (!st.sources.length) {
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
          const click = c.cat && v != null ? `class="cell lv-${lv}" data-file="${esc(f.file_key)}" data-cat="${c.cat}"` : `class="lv-${lv}"`;
          return `<td ${click} title="${esc(c.hint)}">${text}</td>`;
        }).join("")}</tr>`;
      }).join("")}
    </table></div>
    <div class="legend"><span><i class="lv-good"></i>хорошо</span><span><i class="lv-fair"></i>есть что поправить</span><span><i class="lv-bad"></i>плохо</span>
      ${o.trend ? `<span class="muted">· стрелки — с обновления ${esc(day(o.trend.since))}</span>` : isDefault() ? "" : '<span class="muted">· стрелки изменений видны при фильтрах по умолчанию</span>'}</div>`;
  el.querySelectorAll(".task").forEach((c) => (c.onclick = () => (location.hash = `#/colours?cat=${c.dataset.cat}`)));
  el.querySelectorAll("td.cell").forEach((c) => (c.onclick = () => {
    filt.files = c.dataset.file; saveFilter();
    location.hash = `#/colours?cat=${c.dataset.cat}`;
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

const VIEWS = { "": viewOverview, colours: viewColours, sources: viewSources, settings: viewSettings };
// Номер текущего перехода. Медленный ответ предыдущего экрана не должен затереть уже
// открытый следующий: общая картина считается дольше, чем открываются цвета.
let routeSeq = 0;
async function route() {
  const seq = ++routeSeq;
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const name = VIEWS[path] ? path : "";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.v === (name || "overview")));
  const el = $("#view");
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
