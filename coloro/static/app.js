/* coloro — interface.
   Left panel: projects and files. Right panel: what to look at and what to include.
   Center: results. Both panels collapse into floating buttons that keep showing progress and alerts. */

"use strict";

/* ───────────────────── helpers ───────────────────── */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n) => (n == null ? "—" : Number(n).toLocaleString("en-US"));
const pct = (n) => (n == null ? "—" : (Math.round(n * 10) / 10).toLocaleString("en-US") + "%");
const kilo = (n) => (n >= 1e6 ? (Math.round(n / 1e5) / 10) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "K" : String(n || 0));
const pl = (n, one, many) => `${num(n)} ${n === 1 ? one : many || one + "s"}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function day(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}
function ago(iso) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return s < 86400 * 30 ? `${Math.round(s / 86400)} days ago` : day(iso);
}
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const LS = {
  get(k, d) { try { const v = localStorage.getItem("coloro." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("coloro." + k, JSON.stringify(v)); } catch (e) { /* storage is optional */ } },
};
const ICON = {
  open: '<svg class="i" viewBox="0 0 16 16"><path d="M9 3h4v4M13 3 7.5 8.5M12 9.5V13H3V4h3.5"/></svg>',
  copy: '<svg class="i" viewBox="0 0 16 16"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2"/></svg>',
  update: '<svg class="i" viewBox="0 0 16 16"><path d="M13 8a5 5 0 1 1-1.5-3.5M13 3v3h-3"/></svg>',
  more: '<svg class="i" viewBox="0 0 16 16"><circle cx="4" cy="8" r=".8"/><circle cx="8" cy="8" r=".8"/><circle cx="12" cy="8" r=".8"/></svg>',
  download: '<svg class="i" viewBox="0 0 16 16"><path d="M8 2.5v8M4.5 7 8 10.5 11.5 7M3 13.5h10"/></svg>',
};

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty response */ }
  if (!r.ok) throw new Error(data.error || `Server error ${r.status}`);
  return data;
}

function toast(text, kind = "", sticky = false) {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.innerHTML = `<span class="d"></span><span>${esc(text)}</span>${sticky ? '<button class="x" title="Dismiss">×</button>' : ""}`;
  $("#toasts").append(t);
  const close = () => { t.classList.add("out"); setTimeout(() => t.remove(), 260); };
  if (sticky) t.querySelector(".x").onclick = close; else setTimeout(close, kind === "err" ? 6000 : 3200);
  while ($("#toasts").children.length > 4) $("#toasts").firstChild.remove();
}

async function copy(text, what) {
  try { await navigator.clipboard.writeText(text); toast(`Copied ${what}`, "ok"); }
  catch (e) { toast("Could not copy to the clipboard", "err"); }
}

/* ───────────────────── state ───────────────────── */

const DEFAULT_F = { hidden: false, archive: false, instances: true, pages: "", skip: "", since: "", modified_since: "" };
const DEFAULT_SHOW = {
  colors: { view: "colors", cat: "off", usage: "all", family: "", sort: "uses", q: "", rare: 2 },
  gradients: { sort: "uses", q: "" },
  tokens: { cat: "all", q: "" },
  typography: { cat: "unbound" },
  spacing: { group: "spacing", cat: "near" },
  effects: { cat: "unbound" },
  images: { cat: "repeated" },
  components: { cat: "all", q: "" },
};
const S = {
  st: null,
  project: LS.get("project", null),
  type: LS.get("type", "overview"),
  filters: { ...DEFAULT_F, ...LS.get("filters", {}) },
  show: Object.fromEntries(Object.entries(DEFAULT_SHOW).map(([k, v]) => [k, { ...v, ...(LS.get("show", {})[k] || {}) }])),
  off: LS.get("off", {}),          // project → file keys switched off in the left panel
  search: null,                    // active search, or null
  overview: null,
  facets: null,
};
const save = () => { LS.set("project", S.project); LS.set("type", S.type); LS.set("filters", S.filters); LS.set("show", S.show); LS.set("off", S.off); };

const project = () => (S.st ? S.st.projects.find((p) => p.id === S.project) || S.st.projects[0] : null);
const sources = () => (S.st ? S.st.sources.filter((s) => s.project === (project() || {}).id) : []);
const offKeys = () => S.off[S.project] || [];
const activeFilterCount = () => Object.keys(DEFAULT_F).filter((k) => S.filters[k] !== DEFAULT_F[k]).length;

/** Query string for every data request: project, files in scope and filters. */
function fq(extra = {}) {
  const q = new URLSearchParams();
  const p = project();
  if (p) q.set("project", p.id);
  const f = S.filters;
  if (f.hidden) q.set("hidden", "1");
  if (f.archive) q.set("archive", "1");
  if (!f.instances) q.set("instances", "0");
  for (const k of ["pages", "skip", "since", "modified_since"]) if (f[k]) q.set(k, f[k]);
  const off = offKeys();
  if (off.length) {
    const on = [...new Set(sources().map((s) => s.file_key))].filter((k) => !off.includes(k));
    q.set("files", on.length ? on.join(",") : "-");
  }
  for (const [k, v] of Object.entries(extra)) {
    if (Array.isArray(v)) v.forEach((x) => q.append(k, x));
    else if (v !== undefined && v !== null && v !== "") q.set(k, v);
  }
  const s = q.toString();
  return s ? "?" + s : "";
}

/** Search query as request parameters. */
function sq(extra = {}) {
  const s = S.search || {};
  const o = { q: s.q, where: s.where !== "all" ? s.where : "", w: s.w, h: s.h, tol: s.tol, color: s.color, ctol: s.color ? s.ctol : "",
    type: s.type || [], page: s.page || [], comp: s.comp || [], ...extra };
  for (const [k, v] of Object.entries(s.props || {})) o["prop_" + k] = v;
  return fq(o);
}

/* ───────────────────── panels ───────────────────── */

function setClosed(side, closed) {
  document.body.classList.toggle(side + "-closed", closed);
  LS.set("closed." + side, closed);
}
function closePops() { $$(".panel.pop").forEach((p) => p.classList.remove("pop")); }
function fit() { document.body.classList.toggle("compact", innerWidth < 960); if (innerWidth >= 960) closePops(); }
$$("[data-collapse]").forEach((b) => (b.onclick = () => setClosed(b.dataset.collapse, true)));
$$(".mini").forEach((b) => (b.onclick = (e) => {
  const side = b.dataset.open, panel = side === "l" ? $("#left") : $("#right");
  if (document.body.classList.contains("compact")) {
    const was = panel.classList.contains("pop");
    closePops(); panel.classList.toggle("pop", !was); e.stopPropagation(); return;
  }
  setClosed(side, false);
}));
document.addEventListener("click", (e) => {
  if (document.body.classList.contains("compact") && !e.target.closest(".panel,.mini,.cpop")) closePops();
  if (!e.target.closest("#projMenu,#projBtn")) $("#projMenu").classList.remove("on");
  if (!e.target.closest(".fmenu,[data-act=more]")) $$(".fmenu").forEach((m) => m.remove());
  if (!e.target.closest("#cpop,#swBtn")) $("#cpop").hidden = true;
});
addEventListener("resize", fit);

function applyTheme(light) {
  document.body.classList.toggle("light", light);
  document.documentElement.classList.remove("pre-light");
  try { localStorage.setItem("coloro.theme", light ? "light" : "dark"); } catch (e) { /* optional */ }
}
$("#themeBtn").onclick = () => applyTheme(!document.body.classList.contains("light"));

/* ───────────────────── left: projects ───────────────────── */

const projGradient = (id) => {
  const pairs = [["#0c8ce9", "#7b61ff"], ["#14ae5c", "#ffcd29"], ["#f24822", "#ff8a1f"], ["#7b61ff", "#f15bb5"], ["#00b5ce", "#14ae5c"], ["#ffcd29", "#f24822"]];
  const [a, b] = pairs[(id - 1) % pairs.length];
  return `linear-gradient(135deg,${a},${b})`;
};

function drawProject() {
  const p = project();
  if (!p) return;
  S.project = p.id;
  $("#projName").textContent = p.name;
  $("#projMeta").textContent = pl(new Set(sources().map((s) => s.file_key)).size, "file");
  $("#projDot").style.background = projGradient(p.id);
  const m = $("#projMenu");
  m.innerHTML = S.st.projects.map((x) => `<button data-p="${x.id}" class="${x.id === p.id ? "on" : ""}"><span class="pdot" style="background:${projGradient(x.id)}"></span><span class="grow">${esc(x.name)}</span><span class="muted">${x.files}</span></button>`).join("")
    + `<hr><button data-act="new">New project</button><button data-act="rename">Rename project</button><button data-act="delete" class="danger">Delete project</button>`;
  m.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => { S.project = +b.dataset.p; m.classList.remove("on"); S.search = null; save(); syncSearchForm(); refresh(); }));
  m.querySelector("[data-act=new]").onclick = (e) => { e.stopPropagation(); nameForm(m, "", "Create project", async (name) => {
    const r = await api("/api/projects", { name }); S.project = r.id; save(); m.classList.remove("on"); toast(`Project created: ${name}`, "ok"); await refresh();
    setClosed("l", false); $("#addForm").hidden = false; $("#addForm").elements.url.focus();
  }); };
  m.querySelector("[data-act=rename]").onclick = (e) => { e.stopPropagation(); nameForm(m, p.name, "Rename", async (name) => {
    await api("/api/projects/rename", { id: p.id, name }); m.classList.remove("on"); await refresh();
  }); };
  m.querySelector("[data-act=delete]").onclick = async () => {
    if (!confirm(`Delete the project “${p.name}”? Its file links and token library will be removed. Files used by other projects keep their data.`)) return;
    try { await api("/api/projects/remove", { id: p.id }); S.project = null; save(); toast("Project deleted"); await refresh(); }
    catch (err) { toast(err.message, "err"); }
  };
}
function nameForm(menu, value, action, onSave) {
  menu.innerHTML = `<form class="addform" style="padding:6px"><input class="in" name="n" value="${esc(value)}" placeholder="Project name" maxlength="80" required>
    <div class="row"><button class="b main">${esc(action)}</button><button type="button" class="b quiet" data-x>Cancel</button></div></form>`;
  const f = menu.querySelector("form");
  f.elements.n.focus(); f.elements.n.select();
  f.querySelector("[data-x]").onclick = (e) => { e.stopPropagation(); menu.classList.remove("on"); drawProject(); };
  f.onclick = (e) => e.stopPropagation();
  f.onsubmit = async (e) => {
    e.preventDefault();
    try { await onSave(f.elements.n.value.trim()); } catch (err) { toast(err.message, "err"); }
  };
}
$("#projBtn").onclick = (e) => { e.stopPropagation(); const m = $("#projMenu"); const open = !m.classList.contains("on"); drawProject(); m.classList.toggle("on", open); };

/* ───────────────────── left: files ───────────────────── */

function fileHealth(key) {
  const f = S.overview && S.overview.files.find((x) => x.file_key === key);
  if (!f) return "";
  const lv = Object.values(f.metrics.levels || {});
  return lv.includes("bad") ? "bad" : lv.includes("fair") ? "fair" : lv.includes("good") ? "good" : "";
}

function drawFiles() {
  const job = (S.st && S.st.job) || {};
  const off = offKeys();
  const hits = S.search && S.facets ? Object.fromEntries(S.facets.file.map((f) => [f.value, f.count])) : null;
  const list = sources().slice().sort((a, b) => ((a.file && a.file.name) || a.url).localeCompare((b.file && b.file.name) || b.url));
  const solo = off.length && list.filter((s) => !off.includes(s.file_key)).length === 1;
  $("#files").innerHTML = list.length ? list.map((s) => {
    const f = s.file;
    const name = f ? f.name : s.url.replace(/^https?:\/\/(www\.)?figma\.com\/(design|file|proto|board)\//, "").split("/")[0];
    const failed = f ? f.pages.filter((p) => p.status === "failed").length : 0;
    const okPages = f ? f.pages.filter((p) => p.status === "ok").length : 0;
    const cur = f && job.running && job.current ? job.current[f.name] : null;
    const meta = cur ? `Updating · page ${cur.index} of ${cur.total}`
      : !f ? "Not loaded yet"
      : failed ? `<span class="err">${pl(failed, "page")} failed</span>`
      : f.outdated_format ? "Needs an update"
      : `${pl(okPages, "page")} · ${kilo(f.nodes)} layers${s.pages ? " · " + esc(s.pages.join(", ")) : ""}`;
    const on = !off.includes(s.file_key);
    return `<div class="file ${solo && on ? "solo" : ""}" data-key="${esc(s.file_key)}" data-id="${s.id}">
      <input type="checkbox" ${on ? "checked" : ""} title="Include this file">
      <span class="hd ${fileHealth(s.file_key)}"></span>
      <span class="n" title="Show only this file"><b>${esc(name)}</b><small>${meta}</small></span>
      <span>${hits && hits[s.file_key] ? `<span class="hits">${num(hits[s.file_key])}</span>` : ""}<span class="acts">
        <button class="ib sm" data-act="upd" title="Update this file">${ICON.update}</button>
        <a class="ib sm" href="${esc(s.url)}" target="_blank" rel="noopener" title="Open in Figma">${ICON.open}</a>
        <button class="ib sm" data-act="more" title="More">${ICON.more}</button></span></span>
      ${cur ? `<span class="fbar"><i style="width:${Math.round((cur.index / Math.max(1, cur.total)) * 100)}%"></i></span>` : ""}
    </div>`;
  }).join("") : `<div class="empty" style="margin:6px;padding:18px"><b>No files yet</b>Add a link to a Figma file.<br><button class="b main" id="emptyAdd">Add file</button></div>`;
  const ea = $("#emptyAdd");
  if (ea) ea.onclick = () => { $("#addForm").hidden = false; $("#addForm").elements.url.focus(); };
  $$("#files .file").forEach((row) => {
    const key = row.dataset.key;
    row.querySelector("input").onchange = (e) => {
      const set = new Set(offKeys());
      if (e.target.checked) set.delete(key); else set.add(key);
      S.off[S.project] = [...set]; save(); drawFiles(); reload();
    };
    row.querySelector(".n").onclick = () => {
      const all = [...new Set(sources().map((s) => s.file_key))];
      const only = offKeys().length === all.length - 1 && !offKeys().includes(key);
      S.off[S.project] = only ? [] : all.filter((k) => k !== key);
      save(); drawFiles(); reload();
    };
    row.querySelector("[data-act=upd]").onclick = () => startUpdate({ file_key: key, project: S.project });
    row.querySelector("[data-act=more]").onclick = (e) => {
      e.stopPropagation();
      $$(".fmenu").forEach((m) => m.remove());
      const src = sources().find((s) => String(s.id) === row.dataset.id);
      const m = document.createElement("div");
      m.className = "menu on fmenu";
      m.innerHTML = `<form class="addform" style="padding:6px"><span class="label">Page name contains</span>
          <input class="in" name="pages" value="${esc((src.pages || []).join(", "))}" placeholder="All pages">
          <div class="row"><button class="b">Save</button></div></form>
        <hr><button data-x="force">Reload from scratch</button><button data-x="remove" class="danger">Remove from project</button>`;
      row.append(m);
      m.onclick = (ev) => ev.stopPropagation();
      m.querySelector("form").onsubmit = async (ev) => {
        ev.preventDefault();
        const pages = ev.target.elements.pages.value.split(",").map((x) => x.trim()).filter(Boolean);
        try { await api("/api/sources/pages", { id: src.id, pages }); m.remove(); toast("Saved. Update the file to apply."); await refresh(); }
        catch (err) { toast(err.message, "err"); }
      };
      m.querySelector("[data-x=force]").onclick = () => { m.remove(); startUpdate({ file_key: key, project: S.project, force: true }); };
      m.querySelector("[data-x=remove]").onclick = async () => {
        if (!confirm("Remove this file from the project?")) return;
        try { await api("/api/sources/remove", { id: src.id }); m.remove(); toast("File removed"); await refresh(); }
        catch (err) { toast(err.message, "err"); }
      };
    };
  });
  drawJob();
}

$("#allFiles").onclick = () => { S.off[S.project] = []; save(); drawFiles(); reload(); };
$("#addBtn").onclick = () => { const f = $("#addForm"); f.hidden = !f.hidden; if (!f.hidden) f.elements.url.focus(); };
$("#addCancel").onclick = () => { $("#addForm").hidden = true; };
$("#addForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  const pages = f.elements.pages.value.split(",").map((x) => x.trim()).filter(Boolean);
  try {
    const r = await api("/api/sources", { url: f.elements.url.value.trim(), pages, project: S.project });
    f.reset(); f.hidden = true;
    toast("File added");
    await refresh();
    startUpdate({ file_key: r.file_key, project: S.project });
  } catch (err) { toast(err.message, "err"); }
};

/* ───────────────────── update job ───────────────────── */

let lastJob = null;
function drawJob() {
  const j = (S.st && S.st.job) || {};
  const files = sources().map((s) => s.file).filter(Boolean);
  const btn = $("#updBtn");
  document.body.classList.toggle("busy", !!j.running);
  let progress = 0;
  if (j.running) {
    const parts = Object.values(j.current || {}).reduce((n, c) => n + (c.total ? c.index / c.total : 0), 0);
    progress = j.files_total ? Math.min(1, (j.files_done + parts) / j.files_total) : 0;
    $("#jobStatus").textContent = `Updating · ${j.files_done} of ${pl(j.files_total, "file")}`;
    btn.innerHTML = "Stop"; btn.className = "b"; btn.disabled = false;
    btn.onclick = async () => { await api("/api/stop", {}); toast("Stopping after the current page"); };
  } else {
    const last = files.map((f) => f.loaded_at || f.checked_at).filter(Boolean).sort().pop();
    $("#jobStatus").textContent = files.length ? `Updated ${ago(last)}` : "";
    btn.innerHTML = ICON.update + "Update"; btn.className = "b main";
    btn.disabled = !sources().length;
    btn.onclick = () => startUpdate({ project: S.project });
  }
  $("#totalBar").style.width = Math.round(progress * 100) + "%";
  $("#ringL").style.strokeDashoffset = 138.2 * (1 - progress);
  const failed = sources().filter((s) => s.file && s.file.pages.some((p) => p.status === "failed")).length;
  $("#badgeL").textContent = failed; $("#badgeL").classList.toggle("on", failed > 0);
  const p = project();
  $("#tipL").textContent = j.running ? `Updating · ${Math.round(progress * 100)}%`
    : `${p ? p.name : ""} · ${pl(new Set(sources().map((s) => s.file_key)).size, "file")}${failed ? ` · ${pl(failed, "file")} with errors` : ""}`;
}

async function startUpdate(body) {
  try { await api("/api/update", body); toast("Update started"); pollJob(); }
  catch (e) { toast(e.message, "err"); if (/token/i.test(e.message)) openSettings(); }
}

async function pollJob() {
  clearTimeout(pollJob.t);
  try { S.st = await api("/api/state"); } catch (e) { pollJob.t = setTimeout(pollJob, 8000); return; }
  const j = S.st.job || {};
  drawFiles();
  if (lastJob && lastJob.running && !j.running) {
    const reps = j.reports || [];
    const loaded = reps.reduce((n, r) => n + (r.pages_loaded || []).length, 0);
    const changed = reps.filter((r) => (r.pages_loaded || []).length).length;
    const failedFiles = reps.filter((r) => r.status === "failed");
    const failedPages = reps.reduce((n, r) => n + (r.pages_failed || []).length, 0);
    if (j.stopped) toast("Update stopped. Loaded pages are saved.");
    else if (loaded) toast(`Update complete: ${pl(changed, "file")} changed, ${num(reps.length - changed)} unchanged`, "ok");
    else if (!failedFiles.length && !failedPages) toast("Everything is up to date", "ok");
    for (const r of failedFiles) toast(`${r.name || "A file"}: ${r.error}`, "err", true);
    if (failedPages) toast(`${pl(failedPages, "page")} could not be loaded. Run the update again later.`, "err", true);
    await refresh();
  }
  lastJob = j;
  pollJob.t = setTimeout(pollJob, j.running ? 1500 : 10000);
}

/* ───────────────────── right: types and options ───────────────────── */

const TYPES = [
  { k: "overview", t: "Overview", icon: "M2.5 13.5v-5M6.5 13.5v-9M10.5 13.5v-6M13.5 13.5v-11" },
  { k: "colors", t: "Colors", lv: "stray", icon: "M8 2.5a5.5 5.5 0 1 0 0 11c1 0 1.2-.8.8-1.5-.5-.8 0-1.8 1-1.8h1.4a2.3 2.3 0 0 0 2.3-2.3C13.5 4.8 11 2.5 8 2.5Z" },
  { k: "typography", t: "Typography", lv: "text_nostyle_pct", icon: "M3 4h10M8 4v9M5.5 13h5" },
  { k: "spacing", t: "Spacing & radius", lv: "scale_off_pct", icon: "M3 3v10M13 3v10M6 8h4" },
  { k: "effects", t: "Effects", icon: "M4 4h7v7H4zM6 13h7V6" },
  { k: "images", t: "Images", icon: "M2.5 3.5h11v9h-11zM2.5 10l3-3 3 3 2-2 3 3" },
  { k: "components", t: "Components", icon: "M8 2 11 5 8 8 5 5zM8 8l3 3-3 3-3-3z" },
];

function drawTypes() {
  const lv = (S.overview && S.overview.totals && S.overview.totals.levels) || {};
  $("#types").innerHTML = TYPES.map((t) => {
    const l = t.lv && lv[t.lv];
    return `<button class="tbtn ${!S.search && t.k === S.type ? "on" : ""}" data-k="${t.k}" role="tab" aria-label="${t.t}">
      <svg class="i" viewBox="0 0 16 16"><path d="${t.icon}"/></svg>${l === "bad" || l === "fair" ? `<i class="${l}"></i>` : ""}<span class="tt">${t.t}</span></button>`;
  }).join("");
  $$("#types .tbtn").forEach((b) => (b.onclick = () => go(b.dataset.k)));
}

function go(type, show) {
  S.type = type; S.search = null;
  if (show) Object.assign(S.show[show.key || type], show.values || {});
  save(); syncSearchForm(); route();
  if (document.body.classList.contains("compact")) closePops();
}

const chips = (items, active, attr = "cat") => `<div class="chips">${items.map(([k, t, n, extra]) =>
  `<button class="chip ${String(k) === String(active) ? "on" : ""}" data-${attr}="${esc(k)}">${extra || ""}${esc(t)}${n != null ? `<em>${num(n)}</em>` : ""}</button>`).join("")}</div>`;
const seg = (items, active, attr) => `<div class="seg">${items.map(([k, t]) => `<button class="${k === active ? "on" : ""}" data-${attr}="${k}">${esc(t)}</button>`).join("")}</div>`;
const select = (name, items, value) => `<select class="in" data-sel="${name}">${items.map(([k, t]) => `<option value="${k}" ${String(k) === String(value) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;

/** Right panel «Show» section for the current view. */
function drawShow(html, bind) {
  $("#show").innerHTML = html;
  if (bind) bind($("#show"));
}
function bindShow(root, key, onChange) {
  root.querySelectorAll("[data-cat]").forEach((b) => (b.onclick = () => { S.show[key].cat = b.dataset.cat; save(); onChange(); }));
  root.querySelectorAll("[data-sel]").forEach((s) => (s.onchange = () => { S.show[key][s.dataset.sel] = s.value; save(); onChange(); }));
  root.querySelectorAll("[data-q]").forEach((i) => (i.oninput = debounce(() => { S.show[key][i.dataset.q] = i.value.trim(); save(); onChange(); }, 300)));
}

function drawInclude() {
  const f = S.filters;
  const tg = (k, t, on) => `<div class="tg" data-tg="${k}"><span>${t}</span><span class="sw ${on ? "on" : ""}" role="switch" aria-checked="${on}"></span></div>`;
  $("#include").innerHTML = tg("hidden", "Hidden layers", f.hidden) + tg("archive", "Archived pages", f.archive) + tg("instances", "Layers inside instances", f.instances) +
    `<div class="field"><span class="label">Page name contains</span><input class="in" data-f="pages" value="${esc(f.pages)}" placeholder="All pages"></div>
     <div class="field"><span class="label">Exclude sections containing</span><input class="in" data-f="skip" value="${esc(f.skip)}" placeholder="None"></div>
     <div class="field"><span class="label">Layers added since</span><input class="in" type="date" data-f="since" value="${esc(f.since)}"></div>
     <div class="field"><span class="label">Files modified since</span><input class="in" type="date" data-f="modified_since" value="${esc(f.modified_since)}"></div>`;
  $$("#include [data-tg]").forEach((r) => (r.onclick = () => { S.filters[r.dataset.tg] = !S.filters[r.dataset.tg]; save(); drawInclude(); reload(); }));
  $$("#include [data-f]").forEach((i) => (i.oninput = debounce(() => { S.filters[i.dataset.f] = i.value.trim(); save(); badges(); reload(); }, 450)));
  badges();
}
$("#resetF").onclick = () => { S.filters = { ...DEFAULT_F }; save(); drawInclude(); reload(); toast("Filters reset"); };

function badges() {
  const n = activeFilterCount();
  $("#badgeR").textContent = n; $("#badgeR").classList.toggle("on", n > 0);
  $("#resetF").hidden = n === 0;
  const t = S.search ? "Search" : (TYPES.find((x) => x.k === S.type) || TYPES[0]).t;
  $("#tipR").textContent = `${t} · ${n ? pl(n, "filter") + " changed" : "default filters"}`;
}

/* ───────────────────── search bar ───────────────────── */

const form = $("#search");
function syncSearchForm() {
  const s = S.search || {};
  form.elements.q.value = s.q || "";
  form.elements.w.value = s.w || "";
  form.elements.h.value = s.h || "";
  const sw = $("#swPrev");
  sw.className = s.color ? "set" : "";
  sw.style.background = s.color ? colorCss(s.color) : "";
  $("#swBtn").title = s.color ? `Color ${s.color} ± ${s.ctol}` : "Search by color";
  $("#clearSearch").hidden = !S.search;
}
function colorCss(hex) {
  const h = hex.replace("#", "");
  const a = h.length === 8 ? parseInt(h.slice(6), 16) / 255 : 1;
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${Math.round(a * 1000) / 1000})`;
}
form.onsubmit = (e) => {
  e.preventDefault();
  const q = form.elements.q.value.trim(), w = form.elements.w.value.trim(), h = form.elements.h.value.trim();
  const prev = S.search || {};
  if (!q && !w && !h && !prev.color) { S.search = null; syncSearchForm(); route(); return; }
  // A new query starts without narrowing; the «search in» option and tolerances stay.
  S.search = { where: "all", tol: "", ctol: 3, ...prev, q, w, h, type: [], page: [], comp: [], props: {} };
  syncSearchForm(); route();
};
// Enter в любом поле: у формы несколько полей и нет кнопки, сама она по Enter не отправится.
form.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); form.requestSubmit(); } });
$("#clearSearch").onclick = () => { S.search = null; syncSearchForm(); route(); };
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); form.elements.q.focus(); }
  if (e.key === "Escape") { $("#cpop").hidden = true; $("#veil").hidden = true; closePops(); }
});

// Color picker: hex, opacity, tolerance, and an eyedropper where the browser supports it.
const cp = { pick: $("#cpick"), hex: $("#chex"), tol: $("#ctol"), aOn: $("#calphaOn"), a: $("#calpha") };
$("#swBtn").onclick = (e) => {
  e.stopPropagation();
  const pop = $("#cpop");
  if (!pop.hidden) { pop.hidden = true; return; }
  const s = S.search || {};
  const hex = (s.color || "#FF006F").replace("#", "");
  cp.pick.value = "#" + hex.slice(0, 6).toLowerCase();
  cp.hex.value = "#" + hex.slice(0, 6).toUpperCase();
  cp.aOn.checked = hex.length === 8;
  cp.a.value = hex.length === 8 ? Math.round((parseInt(hex.slice(6), 16) / 255) * 100) : 100;
  cp.tol.value = s.ctol || 3;
  syncPicker();
  const r = $("#swBtn").getBoundingClientRect();
  pop.style.top = r.bottom + 8 + "px";
  pop.style.left = Math.max(12, Math.min(innerWidth - 292, r.right - 280)) + "px";
  pop.hidden = false;
};
function syncPicker() {
  $("#ctolV").textContent = cp.tol.value;
  $("#calphaV").textContent = cp.a.value + "%";
  cp.a.disabled = !cp.aOn.checked;
}
cp.pick.oninput = () => { cp.hex.value = cp.pick.value.toUpperCase(); };
cp.hex.oninput = () => { if (/^#?[0-9a-f]{6}$/i.test(cp.hex.value.trim())) cp.pick.value = "#" + cp.hex.value.trim().replace("#", "").toLowerCase(); };
cp.tol.oninput = syncPicker; cp.a.oninput = syncPicker; cp.aOn.onchange = syncPicker;
if (window.EyeDropper) {
  $("#eyedrop").hidden = false;
  $("#eyedrop").onclick = async () => {
    try { const r = await new window.EyeDropper().open(); cp.pick.value = r.sRGBHex; cp.hex.value = r.sRGBHex.toUpperCase(); } catch (e) { /* cancelled */ }
  };
}
$("#capply").onclick = () => {
  let hex = cp.hex.value.trim().replace("#", "").toUpperCase();
  if (!/^[0-9A-F]{6}$/.test(hex)) { toast("Enter a color as #RRGGBB", "err"); return; }
  if (cp.aOn.checked) hex += Math.round((cp.a.value / 100) * 255).toString(16).padStart(2, "0").toUpperCase();
  const q = form.elements.q.value.trim(), w = form.elements.w.value.trim(), h = form.elements.h.value.trim();
  S.search = { where: "all", tol: "", ...(S.search || {}), q, w, h, color: "#" + hex, ctol: cp.tol.value, type: [], page: [], comp: [], props: {} };
  $("#cpop").hidden = true; syncSearchForm(); route();
};
$("#cclear").onclick = () => {
  if (S.search) { S.search.color = ""; if (!S.search.q && !S.search.w && !S.search.h) S.search = null; }
  $("#cpop").hidden = true; syncSearchForm(); route();
};

/* The address keeps the current view and search, so a search can be bookmarked or shared. */
function writeHash() {
  let h = "#/" + (S.search ? "search" : S.type);
  if (S.search) {
    const s = S.search, q = new URLSearchParams();
    for (const k of ["q", "where", "w", "h", "tol", "color", "ctol"]) if (s[k] && !(k === "where" && s[k] === "all") && !(k === "ctol" && !s.color)) q.set(k, s[k]);
    for (const k of ["type", "page", "comp"]) (s[k] || []).forEach((v) => q.append(k, v));
    for (const [k, vs] of Object.entries(s.props || {})) vs.forEach((v) => q.append("prop_" + k, v));
    h += "?" + q.toString();
  }
  if (location.hash !== h) history.replaceState(null, "", h);
}
function readHash() {
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  if (path === "search" && query) {
    const q = new URLSearchParams(query);
    const props = {};
    for (const [k, v] of q) if (k.startsWith("prop_")) (props[k.slice(5)] = props[k.slice(5)] || []).push(v);
    S.search = { q: q.get("q") || "", where: q.get("where") || "all", w: q.get("w") || "", h: q.get("h") || "", tol: q.get("tol") || "",
      color: q.get("color") || "", ctol: q.get("ctol") || 3, type: q.getAll("type"), page: q.getAll("page"), comp: q.getAll("comp"), props };
  } else if (TYPES.some((t) => t.k === path)) {
    S.type = path; S.search = null;
  }
}

/* ───────────────────── center: routing ───────────────────── */

let routeSeq = 0;
async function route() {
  const seq = ++routeSeq;
  const stale = () => seq !== routeSeq;
  drawTypes(); badges(); writeHash();
  const el = $("#content");
  el.innerHTML = '<div class="loading">Loading…</div>';
  const t = S.search ? { k: "search", t: "Search" } : TYPES.find((x) => x.k === S.type) || TYPES[0];
  $("#tname").innerHTML = esc(t.t);
  $("#show").innerHTML = "";
  if (!S.search && S.facets) { S.facets = null; drawFiles(); }
  // В проекте нет файлов — любой экран предлагает добавить файл, а не показывает пустой список.
  const view = !sources().length ? viewOverview : VIEWS[t.k];
  try { await view(el, stale); }
  catch (e) { if (!stale()) el.innerHTML = `<div class="error">${esc(e.message)}</div>`; }
}
const reload = debounce(async () => { await loadOverview(); drawFiles(); drawTypes(); route(); }, 120);

async function loadOverview() {
  try { S.overview = sources().length ? await api("/api/overview" + fq()) : null; } catch (e) { S.overview = null; }
}

async function refresh() {
  S.st = await api("/api/state");
  if (!S.st.projects.some((p) => p.id === S.project)) S.project = S.st.projects[0].id;
  save();
  drawProject();
  await loadOverview();
  drawFiles(); drawInclude();
  route();
}

/* ───────────────────── places: screens → layers ───────────────────── */

function layerTip(p) {
  const rows = [`<div><span class="k">Type</span>${esc(p.type.toLowerCase().replace(/_/g, " "))}</div>`];
  if (p.size) rows.push(`<div><span class="k">Size</span>${esc(p.size)}</div>`);
  if (p.font) rows.push(`<div><span class="k">Font</span>${esc(p.font)}</div>`);
  if (p.paints && p.paints.length) rows.push(`<div><span class="k">Colors</span>${p.paints.map((c) =>
    `<span style="white-space:nowrap;margin-right:6px"><span class="sw2" style="background:#${c.color};opacity:${c.alpha / 100}"></span>#${esc(c.color)}${c.alpha < 100 ? " " + c.alpha + "%" : ""} <span class="muted">${c.slot === "stroke" ? "stroke" : c.kind === "stop" ? "gradient" : "fill"} · ${c.source}</span></span>`).join(" ")}</div>`);
  if (p.sections) rows.push(`<div><span class="k">Section</span>${esc(p.sections)}</div>`);
  const flags = [p.hidden ? "Hidden" : "", p.overridden ? "Overridden instance" : "", p.exact_link ? "" : "Inside an instance: the link opens the instance"].filter(Boolean);
  if (flags.length) rows.push(`<div class="muted">${esc(flags.join(" · "))}</div>`);
  return rows.join("");
}

function layerLine(p, i) {
  const what = p.type === "TEXT" && p.text ? `“${esc(p.text)}”` : esc(p.type.toLowerCase().replace(/_/g, " "));
  return `<div class="place" data-i="${i}"><span class="p"><code>${esc(p.name)}</code><span class="when">${what}${p.size ? " · " + esc(p.size) : ""}</span></span>
    <a href="${esc(p.link)}" target="_blank" rel="noopener">Open ↗</a></div>`;
}

function bindTips(box, items) {
  const tb = $("#tipbox");
  box.querySelectorAll(".place[data-i]").forEach((r) => {
    r.onmouseenter = () => { tb.innerHTML = layerTip(items[+r.dataset.i]); tb.hidden = false; };
    r.onmousemove = (e) => {
      tb.style.left = Math.min(innerWidth - tb.offsetWidth - 12, e.clientX + 14) + "px";
      tb.style.top = Math.min(innerHeight - tb.offsetHeight - 12, e.clientY + 14) + "px";
    };
    r.onmouseleave = () => { tb.hidden = true; };
  });
}

const screenText = (g) => `${g.file} › ${g.page} › ${g.screen} — ${pl(g.count, "match", "matches")}\n${g.link}`;
const layerText = (p) => `${p.name}${p.type === "TEXT" && p.text ? ` — “${p.text}”` : ""}\n${p.link}`;

/** Screens with matches; a screen opens its layers. groupsUrl(offset, limit) and layersUrl(group) build the requests. */
async function screensBlock(box, groupsUrl, layersUrl, emptyHint, offset = 0) {
  if (!offset) box.innerHTML = '<div class="loading">Searching…</div>';
  let d;
  try { d = await api(groupsUrl(offset)); }
  catch (e) { box.innerHTML = `<div class="error">${esc(e.message)}</div>`; return null; }
  if (!offset) {
    box.innerHTML = d.total
      ? `<div class="places-head"><span class="grow">${pl(d.total_places, "match", "matches")} on ${pl(d.total, "screen")}</span>
          <button class="b quiet" data-copyall>${ICON.copy}Copy list</button></div>`
      : `<div class="empty"><b>Nothing found</b>${esc(emptyHint || "Try another query or relax the filters.")}</div>`;
    const ca = box.querySelector("[data-copyall]");
    if (ca) ca.onclick = async (e) => {
      e.stopPropagation();
      try { const all = await api(groupsUrl(0, 2000)); copy(all.items.map(screenText).join("\n\n"), pl(all.items.length, "screen")); }
      catch (err) { toast(err.message, "err"); }
    };
  } else {
    const m = box.querySelector(".more-places");
    if (m) m.remove();
  }
  const start = box.querySelectorAll(".scr").length;
  box.insertAdjacentHTML("beforeend", d.items.map((g, n) => {
    const layers = g.layers.map(esc).join(", ") + (g.more_layers ? ` and ${num(g.more_layers)} more` : "");
    return `<div class="scr" data-n="${start + n}">
      <div class="path">${esc(g.file)}<span class="sep">›</span>${esc(g.page)}<span class="sep">›</span><b>${esc(g.screen)}</b></div>
      <div class="cnt">${pl(g.count, "match", "matches")} · ${layers}</div>
      <div class="acts"><button data-copy title="Copy layers with links">${ICON.copy}</button><a href="${esc(g.link)}" target="_blank" rel="noopener" title="Open the screen in Figma">${ICON.open}</a></div></div>`;
  }).join(""));
  box._groups = (box._groups || []).slice(0, start).concat(d.items);
  box.querySelectorAll(".scr").forEach((h) => {
    if (h.dataset.bound) return;
    h.dataset.bound = "1";
    const g = box._groups[+h.dataset.n];
    h.querySelector("[data-copy]").onclick = async (e) => {
      e.stopPropagation();
      try { const r = await api(layersUrl(g)); copy(`${g.file} › ${g.page} › ${g.screen}\n${g.link}\n\n` + r.items.map(layerText).join("\n\n"), pl(r.items.length, "layer")); }
      catch (err) { toast(err.message, "err"); }
    };
    h.onclick = async (e) => {
      if (e.target.closest("a,button")) return;
      const next = h.nextElementSibling;
      if (next && next.classList.contains("layers")) { next.remove(); h.classList.remove("open"); return; }
      h.classList.add("open");
      const lb = document.createElement("div");
      lb.className = "layers";
      lb.innerHTML = '<div class="loading">Loading layers…</div>';
      h.after(lb);
      try {
        const r = await api(layersUrl(g));
        lb.innerHTML = r.items.map(layerLine).join("") + (r.total > r.items.length ? `<div class="muted" style="padding:5px 8px">and ${num(r.total - r.items.length)} more</div>` : "");
        bindTips(lb, r.items);
      } catch (err) { lb.innerHTML = `<div class="error">${esc(err.message)}</div>`; }
    };
  });
  const left = d.total - (offset + d.items.length);
  if (left > 0) {
    box.insertAdjacentHTML("beforeend", `<button class="b quiet more-places">Show ${num(Math.min(d.limit, left))} more of ${pl(left, "screen")}</button>`);
    box.querySelector(".more-places").onclick = () => screensBlock(box, groupsUrl, layersUrl, emptyHint, offset + d.items.length);
  }
  return d;
}

/** A list of rows; selecting a row opens its places under it. */
function rowsWithPlaces(listEl, items, rowHtml, placesFor, pageSize = 150) {
  let shown = 0;
  const more = () => {
    const chunk = items.slice(shown, shown + pageSize);
    const btn = listEl.querySelector(":scope > .more");
    if (btn) btn.remove();
    listEl.insertAdjacentHTML("beforeend", chunk.map((it, i) => rowHtml(it, shown + i)).join(""));
    shown += chunk.length;
    if (shown < items.length) {
      listEl.insertAdjacentHTML("beforeend", `<button class="b quiet more">Show ${num(Math.min(pageSize, items.length - shown))} more of ${num(items.length - shown)}</button>`);
      listEl.querySelector(":scope > .more").onclick = more;
    }
    listEl.querySelectorAll(".crow:not([data-b])").forEach((r) => {
      r.dataset.b = "1";
      r.onclick = (e) => {
        if (e.target.closest("a,button")) return;
        const next = r.nextElementSibling;
        if (next && next.classList.contains("places")) { next.remove(); r.classList.remove("open"); return; }
        r.classList.add("open");
        const box = document.createElement("div");
        box.className = "places";
        r.after(box);
        placesFor(items[+r.dataset.n], box);
      };
    });
  };
  listEl.innerHTML = "";
  if (!items.length) { listEl.innerHTML = '<div class="empty"><b>Nothing here</b>No items match the current options and filters.</div>'; return; }
  more();
}

/** Places through the generic search: base(item) gives the search kind and its parameters. */
const searchPlaces = (base) => (it, box) => screensBlock(box,
  (offset, limit) => "/api/search" + fq({ ...base(it), offset, limit }),
  (g) => "/api/search" + fq({ ...base(it), file_key: g.file_key, screen: g.screen_id || "" }));
const counts = (n) => `
  <div class="num">${num(n.uses)} <span class="muted">${n.uses === 1 ? n.unit : n.units || n.unit + "s"}</span></div>
  <div class="num c-screens">${num(n.screens)} <span class="muted">${n.screens === 1 ? "screen" : "screens"}</span></div>
  <div class="num c-files">${num(n.files)} <span class="muted">${n.files === 1 ? "file" : "files"}</span></div>`;
const colorPlaces = (c, a) => (it, box) => screensBlock(box,
  (offset, limit) => "/api/screens" + fq({ color: c(it), alpha: a(it), offset, limit }),
  (g) => "/api/places" + fq({ color: c(it), alpha: a(it), file_key: g.file_key, screen: g.screen_id || "" }));

/* ───────────────────── overview ───────────────────── */

const COLUMNS = [
  { key: "stray", title: "Stray colors", hint: "Near token, opacity mismatch and off-system colors", go: ["colors", { key: "colors", values: { view: "colors", cat: "off" } }] },
  { key: "unbound", title: "Unbound colors", hint: "Colors equal to a token but set by hand", go: ["colors", { key: "colors", values: { view: "colors", cat: "unbound" } }] },
  { key: "raw_pct", title: "Set by hand", hint: "Share of color uses without a token or style", pct: true, go: ["colors", { key: "colors", values: { view: "colors", cat: "all" } }] },
  { key: "text_nostyle_pct", title: "Unstyled text", hint: "Share of text placed by hand that has no text style. Text inside instances is set by the library.", pct: true, go: ["typography", { values: { cat: "all" } }] },
  { key: "scale_off_pct", title: "Off-scale", hint: "Share of spacing, radius and stroke values off the scale or close to it", pct: true, go: ["spacing", { values: { cat: "off" } }] },
  { key: "generic", title: "Unnamed layers", hint: "Frames and groups with default names such as Frame 12, placed by hand" },
];
const LOWER_IS_BETTER = new Set(["stray", "raw", "raw_pct", "text_nostyle", "text_nostyle_pct", "generic", "unbound", "scale_off_pct", "scale_off"]);
function trendText(key, d, isPct) {
  if (d == null || d === 0) return "";
  const better = LOWER_IS_BETTER.has(key) ? d < 0 : d > 0;
  return `<span class="${better ? "up" : "dn"}">${d > 0 ? "↑" : "↓"} ${isPct ? pct(Math.abs(d)) : num(Math.abs(d))}</span>`;
}

const HISTORY = [
  { key: "bound_pct", title: "Colors from the system", pct: true, up: true },
  { key: "stray", title: "Stray colors" },
  { key: "raw_pct", title: "Set by hand", pct: true },
  { key: "text_nostyle_pct", title: "Unstyled text", pct: true },
  { key: "scale_off_pct", title: "Off-scale", pct: true },
  { key: "generic", title: "Unnamed layers" },
];
function spark(values, good) {
  const w = 220, h = 40, pad = 4;
  const nums = values.filter((v) => v != null);
  if (nums.length < 2) return "";
  const lo = Math.min(...nums), hi = Math.max(...nums), span = hi - lo || 1;
  const pts = values.map((v, i) => (v == null ? null : [pad + (i * (w - 2 * pad)) / (values.length - 1), h - pad - ((v - lo) * (h - 2 * pad)) / span])).filter(Boolean);
  const color = `var(--${good ? "good" : "bad"}-tx)`;
  const last = pts[pts.length - 1];
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" aria-hidden="true"><path d="${pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("")}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/><circle cx="${last[0]}" cy="${last[1]}" r="2.5" fill="${color}"/></svg>`;
}

async function viewOverview(el, stale) {
  const p = project();
  if (!sources().length) {
    el.innerHTML = `<div class="empty"><b>Add a Figma file to ${esc(p ? p.name : "this project")}</b>Paste a link to a file. coloro loads it and shows what follows the design system and what does not.<br><button class="b main" id="ovAdd">Add file</button></div>`;
    $("#ovAdd").onclick = () => { setClosed("l", false); $("#addForm").hidden = false; $("#addForm").elements.url.focus(); };
    return;
  }
  const o = S.overview || await api("/api/overview" + fq());
  if (stale()) return;
  if (!o.files.length) {
    el.innerHTML = `<div class="empty"><b>Files are not loaded yet</b>The links are added. Load the files from Figma to see the picture.<br><button class="b main" id="ovUpd">Update</button></div>`;
    $("#ovUpd").onclick = () => startUpdate({ project: S.project });
    return;
  }
  const t = o.totals, tr = o.trend && o.trend.total;
  const since = o.trend ? ` since ${day(o.trend.since)}` : "";
  const tile = (title, value, sub, key, isPct, goTo) => {
    const d = tr ? trendText(key, tr[key], isPct) : "";
    return `<button class="tile" ${goTo ? `data-go='${esc(JSON.stringify(goTo))}'` : "disabled"}>
      <div class="t">${title}</div><div class="v">${value}</div><div class="d">${d ? d + since : sub}</div></button>`;
  };
  $("#tname").innerHTML = `Overview<span>${pl(o.files.length, "file")}</span>`;
  el.innerHTML = `
    <div class="head"><div class="grow"><h1>${esc(p.name)}</h1><p class="sub">${pl(o.files.length, "file")} · ${num(t.layers)} layers · ${num(t.uses)} color uses</p></div>
      <a class="b" href="/api/export${fq()}" download id="export">${ICON.download}Download report</a></div>
    ${o.tokens ? "" : `<div class="notice">Load the project’s token library to find stray colors. <a id="ovTok">Open settings</a></div>`}
    <div class="tiles">
      ${tile("Colors from the system", pct(t.bound_pct), "of color uses go through a token or style", "bound_pct", true, ["colors", { key: "colors", values: { view: "colors", cat: "all" } }])}
      ${tile("Stray colors", o.tokens ? num(t.stray) : "—", o.tokens ? `near ${num(t.near)} · opacity ${num(t.alpha)} · off ${num(t.off)}` : "A token library is required", "stray", false, o.tokens ? ["colors", { key: "colors", values: { view: "colors", cat: "off" } }] : null)}
      ${tile("Unbound colors", o.tokens ? num(t.unbound) : "—", "equal to a token, set by hand", "unbound", false, o.tokens ? ["colors", { key: "colors", values: { view: "colors", cat: "unbound" } }] : null)}
      ${tile("Unstyled text", pct(t.text_nostyle_pct), `${num(t.text_nostyle)} texts placed by hand`, "text_nostyle_pct", true, ["typography", { values: { cat: "all" } }])}
      ${tile("Off-scale values", pct(t.scale_off_pct), `${num(t.scale_off)} spacing, radius and stroke values`, "scale_off_pct", true, ["spacing", { values: { cat: "off" } }])}
      ${tile("Unnamed layers", num(t.generic), "frames and groups with default names", "generic", false, null)}
    </div>
    <div id="history"></div>
    <h2>Issues by file</h2>
    <p class="sub">Sorted by severity. Select a cell to see the places in that file.</p>
    <div class="mapw"><table class="map">
      <tr><th>File</th>${COLUMNS.map((c) => `<th title="${esc(c.hint)}">${c.title}</th>`).join("")}</tr>
      ${o.files.map((f) => {
        const m = f.metrics;
        const failed = f.pages.failed ? ` · <span class="dn">${pl(f.pages.failed, "page")} failed</span>` : "";
        return `<tr><td class="f">${esc(f.name)}<small>Modified ${esc(day(f.last_modified))}${failed}</small></td>${COLUMNS.map((c) => {
          const v = m[c.key], lv = m.levels[c.key] || "none";
          const text = v == null ? "—" : c.pct ? pct(v) : num(v);
          const d = o.trend && o.trend.by_file[f.file_key] ? trendText(c.key, o.trend.by_file[f.file_key][c.key], c.pct) : "";
          return `<td class="c lv-${lv} ${c.go && v != null ? "go" : ""}" data-file="${esc(f.file_key)}" data-col="${c.key}" title="${esc(c.hint)}">${text}${d ? " " + d : ""}</td>`;
        }).join("")}</tr>`;
      }).join("")}
    </table></div>
    <div class="legend"><span><i class="lv-good"></i>Good</span><span><i class="lv-fair"></i>Needs attention</span><span><i class="lv-bad"></i>Poor</span>
      ${o.trend ? `<span>Arrows show changes since ${esc(day(o.trend.since))}</span>` : ""}</div>`;
  el.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => { const [type, show] = JSON.parse(b.dataset.go); go(type, show); }));
  const tok = $("#ovTok");
  if (tok) tok.onclick = openSettings;
  $("#export").onclick = () => toast("Building the report. Large projects take up to 20 seconds.");
  el.querySelectorAll("td.go").forEach((c) => (c.onclick = () => {
    const col = COLUMNS.find((x) => x.key === c.dataset.col);
    const all = [...new Set(sources().map((s) => s.file_key))];
    S.off[S.project] = all.filter((k) => k !== c.dataset.file);
    save();
    loadOverview().then(() => { drawFiles(); go(col.go[0], col.go[1]); });
  }));
  drawHistory($("#history"));
}

async function drawHistory(box) {
  const d = await api("/api/history" + fq()).catch(() => null);
  if (!d || !box.isConnected) return;
  const pts = d.points;
  if (pts.length < 2) {
    box.innerHTML = '<p class="sub" style="margin-top:14px">A history chart appears after an update that changes something.</p>';
    return;
  }
  box.innerHTML = `<h2>How it changed</h2><p class="sub">${pl(pts.length, "snapshot")} from ${esc(day(pts[0].taken_at))} to ${esc(day(pts[pts.length - 1].taken_at))}. Green means better, red means worse.</p>
    <div class="tiles">${HISTORY.map((h) => {
      const vals = pts.map((p) => p.metrics[h.key] ?? null);
      const first = vals.find((v) => v != null), last = vals[vals.length - 1];
      if (first == null || last == null) return "";
      const better = h.up ? last >= first : last <= first;
      const diff = last - first;
      const show = (v) => (h.pct ? pct(v) : num(v));
      return `<div class="tile"><div class="t">${h.title}</div><div class="v">${show(last)}</div>
        <div class="d">${diff ? `${diff > 0 ? "+" : "−"}${show(Math.abs(diff))} since ${esc(day(pts[0].taken_at))}` : "No change"}</div>${spark(vals, better)}</div>`;
    }).join("")}</div>`;
}

/* ───────────────────── colors ───────────────────── */

const CCATS = [["near", "Near token"], ["alpha", "Opacity mismatch"], ["off", "Off-system"], ["unbound", "Unbound"], ["rare", "Rare"], ["all", "All"]];
const CHINT = {
  near: "Looks the same as a token. Replace it with the token.",
  alpha: "A token’s color with another opacity. Add a token with this opacity or use an existing one.",
  off: "Far from every token. Add it to the system or replace it.",
  unbound: "Equal to a token but set by hand somewhere. Bind the variable: nothing changes visually.",
  rare: "Used only a few times. Often a typo or a leftover.",
  all: "Every color in use.",
};
const FAMILIES = ["White", "Black", "Neutral", "Red", "Orange", "Yellow", "Green", "Teal", "Blue", "Purple", "Magenta"];
const FAMILY_DOT = { White: "#fff", Black: "#000", Neutral: "#8a8f98", Red: "#f24822", Orange: "#ff8a1f", Yellow: "#ffcd29", Green: "#14ae5c", Teal: "#00b5ce", Blue: "#0c8ce9", Purple: "#7b61ff", Magenta: "#f15bb5" };

function inCat(i, k, rare) {
  if (k === "all") return true;
  if (k === "unbound") return i.unbound;
  if (k === "rare") return i.uses <= rare && i.status !== "token";
  return i.status === k;
}
const swatch = (c, a) => `<span class="sample chk"><i style="background:#${c};opacity:${a / 100}"></i></span>`;
function colourWhat(i) {
  const n = i.nearest;
  const near = n ? `Closest: <b>${esc(n.name)}</b> ${esc(n.label)}${n.de != null ? ` · ΔE ${Math.round(n.de * 10) / 10}` : ""}` : "";
  if (i.status === "token") return `<span class="tag token">Token</span><b>${esc(i.tokens.join(", "))}</b>${i.unbound ? ` · <span class="dn">${num(i.raw)} set by hand</span>` : ""}`;
  if (i.status === "none") return '<span class="muted">No token library</span>';
  const tag = { near: "Near token", alpha: "Opacity mismatch", off: "Off-system" }[i.status];
  return `<span class="tag ${i.status}">${tag}</span>${near}`;
}
const colorViews = () => seg([["colors", "Colors"], ["gradients", "Gradients"], ["tokens", "Tokens"]], S.show.colors.view, "cview");
function bindColorViews(root) {
  root.querySelectorAll("[data-cview]").forEach((b) => (b.onclick = () => { S.show.colors.view = b.dataset.cview; save(); route(); }));
}

async function viewColors(el, stale) {
  const sh = S.show.colors;
  if (sh.view === "gradients") return viewGradients(el, stale);
  if (sh.view === "tokens") return viewTokens(el, stale);
  const d = await api("/api/colours" + fq());
  if (stale()) return;
  if (!d.tokens && ["near", "alpha", "off", "unbound"].includes(sh.cat)) sh.cat = "all";
  const rare = +sh.rare || 2;
  const fileName = Object.fromEntries((S.overview ? S.overview.files : []).map((f) => [f.file_key, (f.name || "").toLowerCase()]));
  const q = (sh.q || "").toLowerCase().replace("#", "");
  const byUsage = (i) => (sh.usage === "fills" ? i.grad === 0 : sh.usage === "gradients" ? i.flat === 0 : sh.usage === "both" ? i.flat > 0 && i.grad > 0 : true);
  const base = d.items.filter((i) => byUsage(i)
    && (!q || i.color.toLowerCase().includes(q) || (i.tokens || []).some((t) => t.toLowerCase().includes(q)) || (i.nearest && i.nearest.name.toLowerCase().includes(q))
      || i.file_keys.some((k) => (fileName[k] || "").includes(q))));
  const cats = CCATS.filter(([k]) => d.tokens || !["near", "alpha", "off", "unbound"].includes(k));
  const inFamily = (i) => !sh.family || i.family === sh.family;
  const items = base.filter((i) => inFamily(i) && inCat(i, sh.cat, rare));
  const sorters = { uses: (a, b) => b.uses - a.uses, files: (a, b) => b.files - a.files || b.uses - a.uses, light: (a, b) => b.lightness - a.lightness,
    family: (a, b) => FAMILIES.indexOf(a.family) - FAMILIES.indexOf(b.family) || b.lightness - a.lightness };
  items.sort(sorters[sh.sort] || sorters.uses);
  const famCount = Object.fromEntries(FAMILIES.map((f) => [f, base.filter((i) => i.family === f && inCat(i, sh.cat, rare)).length]));
  $("#tname").innerHTML = `Colors<span>${pl(d.items.length, "color")}</span>`;
  drawShow(`${colorViews()}
    <div class="sec">Status</div>${chips(cats.map(([k, t]) => [k, t, base.filter((i) => inFamily(i) && inCat(i, k, rare)).length]), sh.cat)}
    <div class="field" style="margin-top:6px"><span class="label">Where it is used</span>${select("usage", [["all", "Fills, strokes and gradients"], ["fills", "Fills and strokes only"], ["gradients", "Gradients only"], ["both", "Both"]], sh.usage)}</div>
    <div class="field"><span class="label">Sort by</span>${select("sort", [["uses", "Most used"], ["files", "Number of files"], ["light", "Lightness"], ["family", "Color family"]], sh.sort)}</div>
    ${sh.cat === "rare" ? `<div class="field"><span class="label">Rare means used at most</span>${select("rare", [[2, "2 times"], [5, "5 times"], [10, "10 times"]], rare)}</div>` : ""}
    <div class="field"><span class="label">Find in the list</span><input class="in" data-q="q" value="${esc(sh.q)}" placeholder="Hex, token or file name"></div>
    <div class="sec">Color family</div>${chips([["", "All"], ...FAMILIES.filter((f) => famCount[f]).map((f) => [f, f, famCount[f], `<span class="dot" style="background:${FAMILY_DOT[f]}"></span>`])], sh.family, "fam")}`,
  (root) => {
    bindShow(root, "colors", () => route());
    bindColorViews(root);
    root.querySelectorAll("[data-fam]").forEach((b) => (b.onclick = () => { sh.family = b.dataset.fam; save(); route(); }));
  });
  el.innerHTML = `<div class="head"><div class="grow"><h1>${esc(CCATS.find(([k]) => k === sh.cat)[1])}${sh.family ? " · " + esc(sh.family) : ""}</h1>
      <p class="sub">${esc(CHINT[sh.cat])} ${pl(items.length, "color")} · ${pl(items.reduce((n, i) => n + i.uses, 0), "use")}</p></div></div>
    ${d.tokens ? "" : `<div class="notice">No token library for this project, so colors cannot be compared with tokens. <a id="cTok">Open settings</a></div>`}
    <div class="list" id="list"></div>`;
  const ct = $("#cTok");
  if (ct) ct.onclick = openSettings;
  rowsWithPlaces($("#list"), items, (i, n) => `<div class="crow" data-n="${n}">${swatch(i.color, i.alpha)}
      <div class="name"><span class="mono">${esc(i.label)}</span><small>${esc(i.family)} · ${i.grad ? `${num(i.flat)} fill · ${num(i.grad)} gradient` : "fills and strokes"}${i.raw ? ` · ${num(i.raw)} set by hand` : ""}${i.first_seen ? " · since " + esc(day(i.first_seen)) : ""}</small></div>
      ${counts({ uses: i.uses, screens: i.screens, files: i.files, unit: "use" })}
      <div class="what">${colourWhat(i)}</div></div>`,
  colorPlaces((i) => i.color, (i) => i.alpha));
}

async function viewGradients(el, stale) {
  const sh = S.show.gradients;
  const d = await api("/api/gradients" + fq());
  if (stale()) return;
  const q = (sh.q || "").toLowerCase().replace("#", "");
  const items = d.items.filter((g) => !q || g.stops.some((s) => s.color.toLowerCase().includes(q)));
  const sorters = { uses: (a, b) => b.uses - a.uses, files: (a, b) => b.files - a.files || b.uses - a.uses, stops: (a, b) => b.stops.length - a.stops.length || b.uses - a.uses };
  items.sort(sorters[sh.sort] || sorters.uses);
  $("#tname").innerHTML = `Colors<span>${pl(d.items.length, "gradient")}</span>`;
  drawShow(`${colorViews()}
    <div class="field" style="margin-top:8px"><span class="label">Sort by</span>${select("sort", [["uses", "Most used"], ["files", "Number of files"], ["stops", "Number of stops"]], sh.sort)}</div>
    <div class="field"><span class="label">Find in the list</span><input class="in" data-q="q" value="${esc(sh.q)}" placeholder="Stop color hex"></div>`,
  (root) => { bindShow(root, "gradients", () => route()); bindColorViews(root); });
  el.innerHTML = `<div class="head"><div class="grow"><h1>Gradients</h1><p class="sub">Each recipe (type and stops in order) is one row. ${pl(items.length, "gradient")} · ${pl(items.reduce((n, g) => n + g.uses, 0), "use")}</p></div></div><div class="list" id="list"></div>`;
  const css = (g) => `${g.kind === "radial" || g.kind === "diamond" ? "radial-gradient(circle" : g.kind === "angular" ? "conic-gradient(from 0deg" : "linear-gradient(90deg"},${g.stops.map((s) => colorCss("#" + s.color + Math.round(s.alpha * 2.55).toString(16).padStart(2, "0"))).join(",")})`;
  rowsWithPlaces($("#list"), items, (g, n) => `<div class="crow" data-n="${n}"><span class="sample chk"><i style="background:${css(g)}"></i></span>
      <div class="name">${esc(g.kind[0].toUpperCase() + g.kind.slice(1))} · ${pl(g.stops.length, "stop")}<small class="stops">${g.stops.map((s) => `<code>#${esc(s.color)}${s.alpha < 100 ? " " + s.alpha + "%" : ""}</code>`).join("")}</small></div>
      ${counts({ uses: g.uses, screens: g.screens, files: g.files, unit: "use" })}
      <div class="what">${g.raw ? `<span class="tag plain">Set by hand</span>${num(g.raw)}` : '<span class="tag token">Style or variable</span>'}${g.first_seen ? " · since " + esc(day(g.first_seen)) : ""}</div></div>`,
  searchPlaces((g) => ({ kind: "gradient", grad: g.id })));
}

async function viewTokens(el, stale) {
  const sh = S.show.tokens;
  const d = await api("/api/tokens/usage" + fq());
  if (stale()) return;
  if (!d.items.length) {
    drawShow(colorViews(), bindColorViews);
    el.innerHTML = `<div class="empty"><b>No token library</b>Load the project’s token library to compare it with the files.<br><button class="b main" id="tTok">Open settings</button></div>`;
    $("#tTok").onclick = openSettings;
    return;
  }
  const q = (sh.q || "").toLowerCase().replace("#", "");
  const base = d.items.filter((t) => !q || t.name.toLowerCase().includes(q) || t.color.toLowerCase().includes(q));
  const cats = [["all", "All"], ["used", "Used"], ["unused", "Unused"]];
  const inT = (t, k) => k === "all" || (k === "used" ? t.uses > 0 : t.uses === 0);
  const items = base.filter((t) => inT(t, sh.cat));
  $("#tname").innerHTML = `Colors<span>${pl(d.items.length, "token")}</span>`;
  drawShow(`${colorViews()}<div class="sec">Usage</div>${chips(cats.map(([k, t]) => [k, t, base.filter((x) => inT(x, k)).length]), sh.cat)}
    <div class="field" style="margin-top:6px"><span class="label">Find in the list</span><input class="in" data-q="q" value="${esc(sh.q)}" placeholder="Token name or hex"></div>`,
  (root) => { bindShow(root, "tokens", () => route()); bindColorViews(root); });
  el.innerHTML = `<div class="head"><div class="grow"><h1>Tokens</h1><p class="sub">The token library against the files. Uses count every color equal to the token value: Figma reports which variable a color is bound to only on the Enterprise plan. Unused tokens may be obsolete.</p></div></div><div class="list" id="list"></div>`;
  rowsWithPlaces($("#list"), items, (t, n) => `<div class="crow" data-n="${n}">${swatch(t.color, t.alpha)}
      <div class="name">${esc(t.name)}<small class="mono">#${esc(t.color)}${t.alpha < 100 ? " · " + t.alpha + "%" : ""}${t.shared ? " · same value as another token" : ""}</small></div>
      ${counts({ uses: t.uses, screens: t.screens, files: t.files, unit: "use" })}
      <div class="what">${t.uses ? (t.raw ? `<span class="tag unbound">Set by hand</span>${num(t.raw)} of ${num(t.uses)}` : '<span class="tag token">Used</span>') : '<span class="tag off">Unused</span>'}</div></div>`,
  (t, box) => (t.uses ? colorPlaces((x) => x.color, (x) => x.alpha)(t, box)
    : (box.innerHTML = '<p class="muted" style="padding:6px 0">This token value is not used in the selected files.</p>')));
}

/* ───────────────────── typography ───────────────────── */

const TCATS = [["unbound", "Unbound"], ["near", "Near style"], ["off", "Off-system"], ["all", "All"]];
const THINT = {
  unbound: "Font, size and line height match a text style, but the style is not applied. Apply it: nothing changes visually.",
  near: "Same font and weight, slightly different size or line height. Often scaled text. Replace it with the style.",
  off: "No such combination in the system. Decide whether a new style is needed or use an existing one.",
  all: "Every font combination in text without a style.",
};
function fontSample(f) {
  const size = Math.max(11, Math.min(f.size || 14, 22));
  return `<span class="sample fsample" style="font-family:'${esc(f.family).replace(/'/g, "")}',sans-serif;font-weight:${f.weight || 400};font-size:${size}px">Aa</span>`;
}
function fontWhat(i) {
  if (i.status === "unbound") return `<span class="tag unbound">Unbound</span>Matches <b>${i.styles.map(esc).join(", ")}</b>`;
  const n = i.nearest;
  if (!n) return `<span class="tag off">Off-system</span>${i.family_known ? `${esc(i.font.family)} is in the system, but not this weight` : `${esc(i.font.family)} is not in the system`}`;
  const diff = [n.dsize ? `size ${n.dsize > 0 ? "+" : ""}${n.dsize}` : "", n.dline ? `line height ${n.dline > 0 ? "+" : ""}${n.dline}` : ""].filter(Boolean).join(", ");
  return `<span class="tag ${i.status}">${i.status === "near" ? "Near style" : "Off-system"}</span>Closest: <b>${esc(n.name)}</b> ${esc(n.label)}${diff ? " · " + diff : ""}`;
}

async function viewTypography(el, stale) {
  const sh = S.show.typography;
  const d = await api("/api/typography" + fq());
  if (stale()) return;
  const sum = (k) => d.items.filter((i) => k === "all" || i.status === k).reduce((n, i) => n + i.uses, 0);
  const items = d.items.filter((i) => sh.cat === "all" || i.status === sh.cat);
  $("#tname").innerHTML = `Typography<span>${pl(sum("all"), "unstyled text")}</span>`;
  drawShow(`<div class="sec">Status</div>${chips(TCATS.map(([k, t]) => [k, t, sum(k)]), sh.cat)}`, (root) => bindShow(root, "typography", () => route()));
  el.innerHTML = `<div class="head"><div class="grow"><h1>${esc(TCATS.find(([k]) => k === sh.cat)[1])}</h1><p class="sub">${esc(THINT[sh.cat])} The system is inferred from the files: ${pl(d.styles.length, "text style")}. Only text placed by hand is counted.</p></div></div>
    <div class="list" id="list"></div>
    <h2>Text styles in the system</h2><p class="sub">The most common font combination of each style.</p>
    <div class="styles">${d.styles.map((s) => `<div class="srow">${fontSample(s.font)}<div class="name">${esc(s.name)}<small>${esc(s.label)}</small></div><div class="num">${num(s.uses)}</div></div>`).join("")}</div>`;
  rowsWithPlaces($("#list"), items, (i, n) => `<div class="crow" data-n="${n}">${fontSample(i.font)}
      <div class="name">${esc(i.label)}<small>${esc(i.font.family)}${i.first_seen ? " · since " + esc(day(i.first_seen)) : ""}</small></div>
      ${counts({ uses: i.uses, screens: i.screens, files: i.files, unit: "text" })}
      <div class="what">${fontWhat(i)}</div></div>`,
  searchPlaces((i) => ({ kind: "font", font: i.font_id })));
}

/* ───────────────────── spacing ───────────────────── */

const SGROUPS = [["spacing", "Spacing"], ["radius", "Radius"], ["stroke", "Stroke"]];
const KIND = { gap: "gap", padding: "padding", radius: "corner", stroke: "stroke" };
function scaleSample(group, v) {
  if (group === "radius") return `<span class="sample"><i style="position:static;width:20px;height:20px;border:1.5px solid var(--txt);border-radius:${Math.min(v, 10)}px"></i></span>`;
  if (group === "stroke") return `<span class="sample"><i style="position:static;width:20px;height:${Math.min(v, 8)}px;background:var(--txt);border:0"></i></span>`;
  return `<span class="sample"><i style="position:static;width:${Math.max(2, Math.min(v, 26))}px;height:14px;background:var(--fair-tx);opacity:.6;border:0"></i></span>`;
}

async function viewSpacing(el, stale) {
  const sh = S.show.spacing;
  const all = await api("/api/scales" + fq());
  if (stale()) return;
  const d = all[sh.group];
  const cats = [["near", "Near scale"], ["off", "Off-scale"], d.source === "variables" ? ["unbound", "Unbound"] : ["ok", "On the grid"], ["all", "All"]];
  if (!cats.some(([k]) => k === sh.cat)) sh.cat = "near";
  const sum = (k) => d.items.filter((i) => k === "all" || i.status === k).reduce((n, i) => n + i.uses, 0);
  const items = d.items.filter((i) => sh.cat === "all" || i.status === sh.cat);
  const tt = d.totals;
  $("#tname").innerHTML = `Spacing & radius<span>${pl(tt.near + tt.off, "value")} off the scale</span>`;
  drawShow(`${seg(SGROUPS, sh.group, "grp")}<div class="sec">Status</div>${chips(cats.map(([k, t]) => [k, t, sum(k)]), sh.cat)}`, (root) => {
    bindShow(root, "spacing", () => route());
    root.querySelectorAll("[data-grp]").forEach((b) => (b.onclick = () => { sh.group = b.dataset.grp; save(); route(); }));
  });
  const scaleLine = d.source === "variables" ? `Scale from bound variables: ${d.scale.map((s) => `<code>${s.value}</code>`).join(" ")}.`
    : sh.group === "spacing" ? "No spacing variables in the files: compared with a 4 px grid (and 2)."
    : sh.group === "radius" ? "No radius variables in the files: even values count as on the grid." : "No stroke variables in the files: 0.5, 1, 1.5, 2, 3 and 4 count as on the grid.";
  el.innerHTML = `<div class="head"><div class="grow"><h1>${esc(SGROUPS.find(([k]) => k === sh.group)[1])} · ${esc(cats.find(([k]) => k === sh.cat)[1])}</h1>
    <p class="sub">${scaleLine} Bound: ${num(tt.bound)}. Set by hand: ${num(tt.ok + tt.unbound + tt.near + tt.off)}.${tt.pill ? ` Pills (radius of half the side): ${num(tt.pill)}.` : ""} Only layers placed by hand are counted.</p></div></div>
    <div class="list" id="list"></div>`;
  rowsWithPlaces($("#list"), items, (i, n) => `<div class="crow" data-n="${n}">${scaleSample(sh.group, i.value)}
      <div class="name">${i.value} px<small>${esc(Object.entries(i.kinds).map(([k, c]) => `${KIND[k] || k} ${num(c)}`).join(" · "))}${i.first_seen ? " · since " + esc(day(i.first_seen)) : ""}</small></div>
      ${counts({ uses: i.uses, screens: i.screens, files: i.files, unit: "use" })}
      <div class="what">${i.status === "unbound" ? '<span class="tag unbound">Unbound</span>On the scale, set as a number' : i.status === "ok" ? '<span class="tag ok">On the grid</span>'
        : `<span class="tag ${i.status}">${i.status === "near" ? "Near scale" : "Off-scale"}</span>Closest: <b>${i.nearest}</b>`}</div></div>`,
  searchPlaces((i) => ({ kind: "prop", group: sh.group, value: i.value })));
}

/* ───────────────────── effects ───────────────────── */

const ECATS = [["unbound", "Unbound"], ["near", "Near style"], ["off", "Off-system"], ["all", "All"]];
function effectSample(e) {
  const c = e.color ? colorCss("#" + e.color + Math.round((e.alpha ?? 100) * 2.55).toString(16).padStart(2, "0")) : "rgba(0,0,0,.25)";
  const style = e.type === "DROP_SHADOW" ? `box-shadow:${e.x || 0}px ${e.y || 0}px ${e.radius || 0}px ${e.spread || 0}px ${c}`
    : e.type === "INNER_SHADOW" ? `box-shadow:inset ${e.x || 0}px ${e.y || 0}px ${e.radius || 0}px ${e.spread || 0}px ${c}`
    : `filter:blur(${Math.min((e.radius || 0) / 4, 4)}px);background:#888`;
  return `<span class="sample eff"><i style="${style}"></i></span>`;
}
async function viewEffects(el, stale) {
  const sh = S.show.effects;
  const d = await api("/api/effects" + fq());
  if (stale()) return;
  const sum = (k) => d.items.filter((i) => k === "all" || i.status === k).reduce((n, i) => n + i.uses, 0);
  const items = d.items.filter((i) => sh.cat === "all" || i.status === sh.cat);
  $("#tname").innerHTML = `Effects<span>${pl(sum("all"), "effect")} set by hand</span>`;
  drawShow(`<div class="sec">Status</div>${chips(ECATS.map(([k, t]) => [k, t, sum(k)]), sh.cat)}`, (root) => bindShow(root, "effects", () => route()));
  el.innerHTML = `<div class="head"><div class="grow"><h1>Effects · ${esc(ECATS.find(([k]) => k === sh.cat)[1])}</h1><p class="sub">Shadows and blurs set by hand, compared with effect styles inferred from the files. With a style: ${num(d.totals.styled)}. Only layers placed by hand are counted.</p></div></div>
    <div class="list" id="list"></div>
    ${d.styles.length ? `<h2>Effects in styles</h2><div class="styles">${d.styles.map((s) => `<div class="srow">${effectSample(s)}<div class="name">${esc(s.styles.join(", "))}<small>${esc(s.label)}${s.color ? " · #" + esc(s.color) : ""}</small></div><div class="num">${num(s.uses)}</div></div>`).join("")}</div>` : ""}`;
  rowsWithPlaces($("#list"), items, (i, n) => `<div class="crow" data-n="${n}">${effectSample(i)}
      <div class="name">${esc(i.label)}<small>${[i.color ? `<span class="mono">#${esc(i.color)}${i.alpha != null && i.alpha < 100 ? " " + i.alpha + "%" : ""}</span>` : "", i.first_seen ? "since " + esc(day(i.first_seen)) : ""].filter(Boolean).join(" · ")}</small></div>
      ${counts({ uses: i.uses, screens: i.screens, files: i.files, unit: "layer" })}
      <div class="what">${i.status === "unbound" ? `<span class="tag unbound">Unbound</span>Matches <b>${i.styles.map(esc).join(", ")}</b>`
        : i.status === "near" ? `<span class="tag near">Near style</span><b>${i.styles.map(esc).join(", ")}</b> · ${esc(i.nearest)}` : '<span class="tag off">Off-system</span>'}</div></div>`,
  searchPlaces((i) => ({ kind: "effect", type: i.type, color: i.color ?? "", alpha: i.alpha ?? "", x: i.x ?? "", y: i.y ?? "", radius: i.radius ?? "", spread: i.spread ?? "" })));
}

/* ───────────────────── images ───────────────────── */

const MODES = { FILL: "fill", FIT: "fit", CROP: "crop", TILE: "tile", STRETCH: "stretch" };
async function viewImages(el, stale) {
  const sh = S.show.images;
  const d = await api("/api/images" + fq());
  if (stale()) return;
  const cats = [["repeated", "Repeated", d.items.filter((i) => i.uses > 1).length], ["once", "Used once", d.once], ["all", "All", d.total]];
  const items = d.items.filter((i) => sh.cat === "all" || (sh.cat === "once" ? i.uses === 1 : i.uses > 1));
  $("#tname").innerHTML = `Images<span>${pl(d.total, "image")}</span>`;
  drawShow(`<div class="sec">Show</div>${chips(cats, sh.cat)}`, (root) => bindShow(root, "images", () => route()));
  el.innerHTML = `<div class="head"><div class="grow"><h1>Images</h1><p class="sub">${pl(d.total, "image")} in ${pl(d.total_uses, "place")}; ${num(d.once)} used once. One image in several places is one row, so repeats and leftover placeholders stand out.${d.total > d.items.length ? ` Showing the ${num(d.items.length)} most used.` : ""}</p></div></div>
    <div class="list" id="list"></div>`;
  rowsWithPlaces($("#list"), items, (i, n) => `<div class="crow" data-n="${n}"><span class="sample thumb" data-ref="${esc(i.ref)}" data-file="${esc(i.file_key)}"></span>
      <div class="name">${esc(i.name)}<small>${i.modes.map((m) => MODES[m] || m.toLowerCase()).join(", ")} · up to ${num(i.max_w)} × ${num(i.max_h)}${i.first_seen ? " · since " + esc(day(i.first_seen)) : ""}</small></div>
      ${counts({ uses: i.uses, screens: i.screens, files: i.files, unit: "place" })}
      <div class="what">${i.uses > 1 ? `<span class="tag near">Repeated</span>${pl(i.uses, "place")}` : '<span class="tag plain">Used once</span>'}</div></div>`,
  searchPlaces((i) => ({ kind: "image", ref: i.ref })));
  // Thumbnails: Figma gives image URLs per file, so one request per file.
  const byFile = {};
  $$(".thumb", el).forEach((t) => (byFile[t.dataset.file] = byFile[t.dataset.file] || []).push(t));
  for (const [fk, thumbs] of Object.entries(byFile)) {
    api("/api/image-urls" + fq({ file_key: fk })).then((r) => {
      if (stale()) return;
      thumbs.forEach((t) => { const u = r.urls[t.dataset.ref]; if (u) t.innerHTML = `<img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer">`; });
    }).catch(() => { /* thumbnails are optional */ });
  }
}

/* ───────────────────── components ───────────────────── */

async function viewComponents(el, stale) {
  const sh = S.show.components;
  const [c, det] = await Promise.all([api("/api/components" + fq({ q: sh.q })), api("/api/detached" + fq())]);
  if (stale()) return;
  const inst = c.items.reduce((n, g) => n + g.instances, 0);
  const over = c.items.filter((g) => g.overridden > 0);
  const cats = [["all", "All", c.items.length], ["overridden", "Overridden", over.length], ["detached", "Possibly detached", det.total]];
  $("#tname").innerHTML = `Components<span>${pl(inst, "instance")}</span>`;
  drawShow(`<div class="sec">Show</div>${chips(cats, sh.cat)}
    <div class="field" style="margin-top:6px"><span class="label">Component or set name</span><input class="in" data-q="q" value="${esc(sh.q)}" placeholder="All components"></div>`,
  (root) => bindShow(root, "components", () => route()));
  if (sh.cat === "detached") {
    el.innerHTML = `<div class="head"><div class="grow"><h1>Possibly detached</h1><p class="sub">Frames and groups named like a component of the file but not instances. A detached instance keeps the component name. This is a hint, not a verdict: a regular frame can have the same name.${det.capped ? ` Showing the first ${num(det.total)}.` : ""}</p></div></div>
      <div class="list">${det.items.length ? det.items.map((d) => `<div class="place"><span class="p">${esc(d.file)} <span class="muted">›</span> ${esc(d.page)} <span class="muted">›</span> ${esc(d.screen)} <span class="muted">›</span> <code>${esc(d.name)}</code></span><a href="${esc(d.link)}" target="_blank" rel="noopener">Open ↗</a></div>`).join("") : '<div class="empty"><b>Nothing found</b>No frames look like detached instances.</div>'}</div>`;
    return;
  }
  const items = sh.cat === "overridden" ? over.slice().sort((a, b) => b.overridden - a.overridden) : c.items;
  el.innerHTML = `<div class="head"><div class="grow"><h1>${sh.cat === "overridden" ? "Overridden instances" : "Components in use"}</h1><p class="sub">${pl(c.total, "set or component", "sets and components")} · ${pl(inst, "instance")}. Open a row to filter by variant properties and see where they are used.</p></div></div>
    <div class="list" id="list"></div>`;
  rowsWithPlaces($("#list"), items, (g, n) => `<div class="crow" data-n="${n}"><span class="sample"><svg class="i" viewBox="0 0 16 16"><path d="M8 2 11 5 8 8 5 5zM8 8l3 3-3 3-3-3z"/></svg></span>
      <div class="name">${esc(g.title)}<small>${g.remote ? "Library" : "Local"} · ${Object.keys(g.variants).length ? Object.entries(g.variants).map(([k, vs]) => `${esc(k)}: ${Object.keys(vs).length}`).join(" · ") : "No variants"}</small></div>
      ${counts({ uses: g.instances, screens: g.screens, files: g.files, unit: "instance" })}
      <div class="what">${g.overridden ? `<span class="tag near">Overridden</span>${pct((g.overridden * 100) / g.instances)} of instances` : '<span class="muted">Not overridden</span>'}</div></div>`,
  (g, box) => openComponent(box, g, {}));
}

function openComponent(box, g, chosen) {
  const facets = Object.entries(g.variants).map(([k, vs]) => `<div class="vchips" style="margin-left:0"><span class="label" style="margin-right:4px">${esc(k)}</span>
    ${Object.entries(vs).sort((a, b) => b[1] - a[1]).map(([v, n]) => `<button class="chip ${chosen[k] === v ? "on" : ""}" data-k="${esc(k)}" data-v="${esc(v)}">${esc(v)}<em>${num(n)}</em></button>`).join("")}</div>`).join("");
  box.innerHTML = `${facets}<div class="kres"></div>`;
  box.querySelectorAll("[data-k]").forEach((b) => (b.onclick = (e) => {
    e.stopPropagation();
    const next = { ...chosen };
    if (next[b.dataset.k] === b.dataset.v) delete next[b.dataset.k]; else next[b.dataset.k] = b.dataset.v;
    openComponent(box, g, next);
  }));
  // Several variant properties at once go through the combined search.
  const q = { comp: [g.set || g.cname] };
  for (const [k, v] of Object.entries(chosen)) q["prop_" + k] = [v];
  screensBlock(box.querySelector(".kres"), (offset, limit) => "/api/find" + fq({ ...q, offset, limit }),
    (gr) => "/api/find/layers" + fq({ ...q, file_key: gr.file_key, screen: gr.screen_id || "" }));
}

/* ───────────────────── search results ───────────────────── */

const TYPE_NAMES = { text: "Text", frame: "Frames and groups", instance: "Instances", component: "Components", shape: "Shapes", other: "Other" };

async function viewSearch(el, stale) {
  const s = S.search;
  el.innerHTML = '<div id="res"></div>';
  const box = $("#res");
  const parts = [s.q ? `“${s.q}”` : "", s.w || s.h ? `${s.w || "any"} × ${s.h || "any"}${s.tol ? " ± " + s.tol : ""}` : "", s.color ? `${s.color} ± ${s.ctol}` : ""].filter(Boolean);
  const d = await screensBlock(box, (offset, limit) => "/api/find" + sq({ offset, limit }), (g) => "/api/find/layers" + sq({ file_key: g.file_key, screen: g.screen_id || "" }),
    "Try other words, a larger tolerance, or include hidden layers and archived pages.");
  if (stale() || !d) return;
  box.insertAdjacentHTML("afterbegin", `<div class="head"><div class="grow"><h1>Search</h1><p class="sub">${esc(parts.join(" · "))}${d.info && d.info.colours != null ? ` · ${pl(d.info.colours, "matching color value")}` : ""}</p></div></div>`);
  S.facets = d.facets;
  drawFiles();
  $("#tname").innerHTML = `Search<span>${pl(d.total_places, "match", "matches")}</span>`;
  const facet = (title, key, list, label = (v) => v) => (list.length ? `<div class="sec">${title}</div><div class="facet" data-facet="${key}">${list.map((f) =>
    `<label><input type="checkbox" value="${esc(f.value)}" ${(s[key] || []).includes(String(f.value)) ? "checked" : ""}><span>${esc(label(f.value))}</span><em>${num(f.count)}</em></label>`).join("")}</div>` : "");
  const props = Object.entries(d.facets.props).map(([k, list]) => `<div class="sec">${esc(k)}</div><div class="facet" data-prop="${esc(k)}">${list.map((f) =>
    `<label><input type="checkbox" value="${esc(f.value)}" ${((s.props || {})[k] || []).includes(f.value) ? "checked" : ""}><span>${esc(f.value)}</span><em>${num(f.count)}</em></label>`).join("")}</div>`).join("");
  drawShow(`<div class="field"><span class="label">Search text in</span>${select("where", [["all", "Text, layer and component names"], ["text", "Text only"], ["name", "Layer names only"], ["component", "Component names only"]], s.where || "all")}</div>
    <div class="field"><span class="label">Size tolerance, px</span><input class="in" data-o="tol" value="${esc(s.tol || "")}" placeholder="0.5" inputmode="decimal"></div>
    ${facet("Type", "type", d.facets.type, (v) => TYPE_NAMES[v] || v)}
    ${facet("Component", "comp", d.facets.comp)}${props}
    ${facet("Page", "page", d.facets.page)}`,
  (root) => {
    root.querySelector("[data-sel=where]").onchange = (e) => { s.where = e.target.value; route(); };
    root.querySelector("[data-o=tol]").oninput = debounce((e) => { s.tol = e.target.value.trim(); route(); }, 450);
    root.querySelectorAll("[data-facet] input").forEach((i) => (i.onchange = () => {
      const k = i.closest("[data-facet]").dataset.facet;
      s[k] = [...i.closest("[data-facet]").querySelectorAll("input:checked")].map((x) => x.value);
      route();
    }));
    root.querySelectorAll("[data-prop] input").forEach((i) => (i.onchange = () => {
      const k = i.closest("[data-prop]").dataset.prop;
      s.props = { ...(s.props || {}), [k]: [...i.closest("[data-prop]").querySelectorAll("input:checked")].map((x) => x.value) };
      if (!s.props[k].length) delete s.props[k];
      route();
    }));
  });
}

/* ───────────────────── settings ───────────────────── */

function openSettings() {
  const st = S.st, p = project();
  const t = p.tokens;
  $("#dlgBody").innerHTML = `
    <h4>Figma access token</h4>
    <p>${st.figma_token ? "Set. It is stored only on this computer, in a file readable by your account only." : "Not set. coloro needs it to load files."}
      Create one in Figma: Settings → Security → Personal access tokens, with read access to files.</p>
    <div class="row"><input class="in" type="password" id="tok" placeholder="${st.figma_token ? "Paste a new token to replace it" : "figd_…"}" autocomplete="off"><button class="b main" id="saveTok">Save</button></div>
    <h4>Token library · ${esc(p.name)}</h4>
    <p>${t.count ? `${esc(t.file)} · ${pl(t.count, "token")} · loaded ${esc(ago(t.loaded_at))}.` : "Not loaded. coloro compares colors with it to find stray colors."}
      W3C Design Tokens, Tokens Studio, a variables export or a CSV with name and value columns.</p>
    <div class="row"><input class="in" type="file" id="tfile" accept=".json,.csv,.txt,application/json,text/csv"><button class="b main" id="upTok">Load</button></div>
    <h4>Updates</h4>
    <div class="row"><span class="grow label">Files downloaded in parallel</span><span style="width:80px">${select("workers", [1, 2, 3, 4, 5, 6, 7, 8].map((n) => [n, String(n)]), st.settings.workers)}</span></div>
    <p style="margin-top:6px">More is faster but closer to the Figma rate limit. 4 is a safe default.</p>
    <div class="row"><button class="b" id="forceAll">Reload all project files from scratch</button></div>`;
  $("#veil").hidden = false;
  $("#saveTok").onclick = async () => {
    const v = $("#tok").value.trim();
    if (!v) { toast("Paste the token first", "err"); return; }
    try { await api("/api/figma-token", { token: v }); $("#tok").value = ""; toast("Token saved", "ok"); S.st = await api("/api/state"); openSettings(); }
    catch (e) { toast(e.message, "err"); }
  };
  $("#upTok").onclick = async () => {
    const f = $("#tfile").files[0];
    if (!f) { toast("Choose a token library file", "err"); return; }
    try {
      const r = await api("/api/tokens", { filename: f.name, text: await f.text(), project: p.id });
      toast(`Loaded ${pl(r.names, "token")}`, "ok");
      $("#veil").hidden = true; await refresh();
    } catch (e) { toast(e.message, "err"); }
  };
  $("#dlgBody [data-sel=workers]").onchange = async (e) => {
    try { await api("/api/settings", { workers: +e.target.value }); toast("Saved"); S.st = await api("/api/state"); }
    catch (err) { toast(err.message, "err"); }
  };
  $("#forceAll").onclick = () => { $("#veil").hidden = true; startUpdate({ project: S.project, force: true }); };
}
$("#gear").onclick = openSettings;
$("#closeDlg").onclick = () => { $("#veil").hidden = true; };
$("#veil").onclick = (e) => { if (e.target.id === "veil") $("#veil").hidden = true; };

/* ───────────────────── start ───────────────────── */

const VIEWS = { overview: viewOverview, colors: viewColors, typography: viewTypography, spacing: viewSpacing, effects: viewEffects,
  images: viewImages, components: viewComponents, search: viewSearch };

addEventListener("hashchange", () => { readHash(); syncSearchForm(); route(); });
(async function start() {
  applyTheme(document.documentElement.classList.contains("pre-light"));
  if (LS.get("closed.l", false)) document.body.classList.add("l-closed");
  if (LS.get("closed.r", false)) document.body.classList.add("r-closed");
  fit();
  readHash();
  syncSearchForm();
  try { await refresh(); }
  catch (e) { $("#content").innerHTML = `<div class="error">${esc(e.message)}</div>`; }
  pollJob();
})();
