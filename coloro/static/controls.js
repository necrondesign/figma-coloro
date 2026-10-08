/* Dropdowns and the date picker in the style of the app, instead of the system ones.

   Selects: the <select> stays in the page, hidden, and keeps the value; a button shows the
   choice and opens a menu. Choosing an item sets the select and fires "change", so the code
   of the views works with it as with any select.

   Dates: <input type="hidden" data-date> keeps the value as YYYY-MM-DD; the button next to
   it opens a month calendar. Choosing a day sets the input and fires "input". */

"use strict";

const Controls = (() => {
  const ru = () => I18N.lang === "ru";
  let pop = null, closeHook = null;

  function close() {
    if (pop) { pop.remove(); pop = null; }
    if (closeHook) { const h = closeHook; closeHook = null; h(); }
  }
  function place(el, anchor, minWidth = true) {
    const r = anchor.getBoundingClientRect();
    if (minWidth) el.style.minWidth = r.width + "px";
    document.body.appendChild(el);
    const h = el.offsetHeight, w = el.offsetWidth;
    const below = innerHeight - r.bottom - 8, above = r.top - 8;
    const top = below >= h || below >= above ? r.bottom + 4 : r.top - h - 4;
    el.style.top = Math.max(8, Math.min(top, innerHeight - h - 8)) + "px";
    el.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px";
  }
  addEventListener("mousedown", (e) => { if (pop && !pop.contains(e.target) && !e.target.closest(".sel-btn,.date-btn")) close(); }, true);
  addEventListener("scroll", (e) => { if (pop && !pop.contains(e.target)) close(); }, true);
  addEventListener("resize", close);

  // ---------------------------------------------------------------- selects
  const CHECK = '<svg class="i" viewBox="0 0 16 16"><path d="m3.5 8.5 3 3 6-6.5"/></svg>';

  function label(sel) {
    const o = sel.options[sel.selectedIndex];
    return o ? o.textContent : "";
  }
  function enhanceSelect(sel) {
    if (sel.dataset.enhanced) return;
    sel.dataset.enhanced = "1";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "in sel-btn";
    btn.setAttribute("aria-haspopup", "listbox");
    btn.innerHTML = `<span class="sel-v"></span>`;
    const sync = () => { btn.querySelector(".sel-v").textContent = label(sel); btn.disabled = sel.disabled; };
    sync();
    sel.after(btn);
    sel.classList.add("sel-native");
    sel.addEventListener("change", sync);
    // Options are translated after they are drawn: keep the button in step.
    new MutationObserver(sync).observe(sel, { childList: true, subtree: true, characterData: true });
    btn.onclick = () => (pop && btn.classList.contains("open") ? close() : openSelect(sel, btn));
    btn.onkeydown = (e) => {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key) && !pop) { e.preventDefault(); openSelect(sel, btn); }
    };
  }
  function openSelect(sel, btn) {
    close();
    const m = document.createElement("div");
    m.className = "dd";
    m.setAttribute("role", "listbox");
    m.innerHTML = [...sel.options].map((o, i) => `<button type="button" class="dd-i ${i === sel.selectedIndex ? "on" : ""}" data-i="${i}" role="option"
      ${o.disabled ? "disabled" : ""}><span class="dd-t"></span>${i === sel.selectedIndex ? CHECK : ""}</button>`).join("");
    [...sel.options].forEach((o, i) => { m.querySelector(`[data-i="${i}"] .dd-t`).textContent = o.textContent; });
    place(m, btn);
    pop = m;
    btn.classList.add("open");
    closeHook = () => { btn.classList.remove("open"); btn.focus({ preventScroll: true }); };
    const items = [...m.querySelectorAll(".dd-i:not([disabled])")];
    let cur = Math.max(0, items.findIndex((b) => b.classList.contains("on")));
    const focus = () => { items[cur].focus({ preventScroll: true }); items[cur].scrollIntoView({ block: "nearest" }); };
    focus();
    m.onclick = (e) => {
      const it = e.target.closest(".dd-i");
      if (!it || it.disabled) return;
      const i = +it.dataset.i;
      close();
      if (i !== sel.selectedIndex) { sel.selectedIndex = i; sel.dispatchEvent(new Event("change", { bubbles: true })); }
    };
    m.onkeydown = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); cur = Math.min(items.length - 1, cur + 1); focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); cur = Math.max(0, cur - 1); focus(); }
      else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); close(); }
    };
  }

  // ---------------------------------------------------------------- dates
  const MONTHS = {
    en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    ru: ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"],
  };
  const DAYS = { en: ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"], ru: ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"] };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const parse = (v) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v || ""); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; };
  const show = (v) => { const d = parse(v); return d ? d.toLocaleDateString(ru() ? "ru-RU" : "en-GB", { day: "numeric", month: "short", year: "numeric" }) : ""; };

  function enhanceDate(inp) {
    if (inp.dataset.enhanced) return;
    inp.dataset.enhanced = "1";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "in date-btn";
    btn.innerHTML = `<span class="sel-v"></span><svg class="i" viewBox="0 0 16 16"><path d="M3 4.5h10v8.5H3zM3 7.5h10M5.5 3v3M10.5 3v3"/></svg>`;
    const sync = () => {
      const v = show(inp.value);
      btn.querySelector(".sel-v").textContent = v || (ru() ? "Любая дата" : "Any date");
      btn.classList.toggle("is-empty", !v);
    };
    sync();
    inp.after(btn);
    inp.addEventListener("input", sync);
    btn.onclick = () => (pop && btn.classList.contains("open") ? close() : openDate(inp, btn, sync));
  }
  function openDate(inp, btn, sync) {
    close();
    const L = ru() ? "ru" : "en";
    const chosen = parse(inp.value);
    let view = chosen ? new Date(chosen) : new Date();
    view.setDate(1);
    const m = document.createElement("div");
    m.className = "dd dp";
    const set = (v) => { inp.value = v; sync(); inp.dispatchEvent(new Event("input", { bubbles: true })); close(); };
    const draw = () => {
      const y = view.getFullYear(), mo = view.getMonth();
      const first = (new Date(y, mo, 1).getDay() + 6) % 7;          // неделя с понедельника
      const days = new Date(y, mo + 1, 0).getDate();
      const today = iso(new Date()), sel = chosen ? iso(chosen) : "";
      let cells = "";
      for (let i = 0; i < first; i++) cells += "<span></span>";
      for (let d = 1; d <= days; d++) {
        const v = iso(new Date(y, mo, d));
        cells += `<button type="button" class="dp-d ${v === sel ? "on" : ""} ${v === today ? "today" : ""}" data-v="${v}">${d}</button>`;
      }
      m.innerHTML = `<div class="dp-h"><button type="button" class="ib sm" data-step="-1" aria-label="${L === "ru" ? "Предыдущий месяц" : "Previous month"}"><svg class="i" viewBox="0 0 16 16"><path d="M10 3.5 5.5 8l4.5 4.5"/></svg></button>
        <b class="grow">${MONTHS[L][mo]} ${y}</b>
        <button type="button" class="ib sm" data-step="1" aria-label="${L === "ru" ? "Следующий месяц" : "Next month"}"><svg class="i" viewBox="0 0 16 16"><path d="m6 3.5 4.5 4.5L6 12.5"/></svg></button></div>
        <div class="dp-w">${DAYS[L].map((d) => `<span>${d}</span>`).join("")}</div>
        <div class="dp-g">${cells}</div>
        <div class="dp-f"><button type="button" class="link" data-today>${L === "ru" ? "Сегодня" : "Today"}</button>
          <button type="button" class="link quiet" data-clear>${L === "ru" ? "Очистить" : "Clear"}</button></div>`;
    };
    draw();
    m.setAttribute("data-u", "");                     // already in the interface language
    m.onclick = (e) => {
      const step = e.target.closest("[data-step]");
      if (step) { view.setMonth(view.getMonth() + +step.dataset.step); draw(); return; }
      const d = e.target.closest("[data-v]");
      if (d) return set(d.dataset.v);
      if (e.target.closest("[data-today]")) return set(iso(new Date()));
      if (e.target.closest("[data-clear]")) return set("");
    };
    m.onkeydown = (e) => { if (e.key === "Escape") close(); };
    place(m, btn, false);
    pop = m;
    btn.classList.add("open");
    closeHook = () => btn.classList.remove("open");
  }

  // ---------------------------------------------------------------- everywhere
  function enhance(root) {
    if (!root || root.nodeType !== 1) return;
    const sels = root.matches?.("select.in") ? [root] : [...root.querySelectorAll("select.in")];
    sels.forEach(enhanceSelect);
    const dates = root.matches?.("input[data-date]") ? [root] : [...root.querySelectorAll("input[data-date]")];
    dates.forEach(enhanceDate);
  }
  function start() {
    enhance(document.body);
    new MutationObserver((list) => { for (const m of list) for (const n of m.addedNodes) enhance(n); })
      .observe(document.body, { childList: true, subtree: true });
    addEventListener("keydown", (e) => { if (e.key === "Escape" && pop) close(); });
  }
  return { start, close };
})();
