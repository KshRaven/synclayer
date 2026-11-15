"use strict";
/* Synclayer web app: files, recent, starred, shared links, trash, admin */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) { if (kid == null) continue; e.append(kid.nodeType ? kid : document.createTextNode(String(kid))); }
  return e;
}
const qs = (o) => new URLSearchParams(Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v != null && v !== false))).toString();
const joinPath = (a, b) => [a, b].filter(Boolean).join("/");
const parentOf = (p) => p.split("/").slice(0, -1).join("/");
const baseName = (p) => p.split("/").pop();

/* ---------- icons (24x24 material-style paths) ---------- */
const P = {
  people: "M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z",
  plus: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z", folder: "M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8z",
  folderplus: "M20 6h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2zm-1 8h-3v3h-2v-3h-3v-2h3V9h2v3h3z",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zm-1 7V3.5L18.5 9z",
  edit: "M3 17.25V21h3.75L17.8 9.94l-3.75-3.75zM20.7 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75z",
  upload: "M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z", download: "M5 20h14v-2H5zM19 9h-4V3H9v6H5l7 7z",
  clock: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm.5 5v5.25l4.5 2.67-.75 1.23L11 13V7z",
  star: "M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z",
  starout: "M22 9.24l-7.19-.62L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.63-7.03zM12 15.4l-3.76 2.27 1-4.28-3.32-2.88 4.38-.38L12 6.1l1.71 4.04 4.38.38-3.32 2.88 1 4.28z",
  link: "M3.9 12a3.1 3.1 0 0 1 3.1-3.1h4V7H7a5 5 0 0 0 0 10h4v-1.9H7A3.1 3.1 0 0 1 3.9 12zM8 13h8v-2H8zm9-6h-4v1.9h4a3.1 3.1 0 0 1 0 6.2h-4V17h4a5 5 0 0 0 0-10z",
  trash: "M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z",
  admin: "M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11z",
  menu: "M3 18h18v-2H3zm0-5h18v-2H3zm0-7v2h18V6z", search: "M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
  theme: "M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.39 5.39 0 0 1-4.4 2.26 5.4 5.4 0 0 1-5.4-5.4c0-1.81.89-3.42 2.26-4.4A9.1 9.1 0 0 0 12 3z",
  gear: "M19.14 12.94c.04-.3.06-.61.06-.94s-.02-.64-.07-.94l2.03-1.58a.5.5 0 0 0 .12-.61l-1.92-3.32a.5.5 0 0 0-.59-.22l-2.39.96a7 7 0 0 0-1.62-.94l-.36-2.54a.48.48 0 0 0-.48-.41h-3.84a.48.48 0 0 0-.48.41l-.36 2.54a7.4 7.4 0 0 0-1.62.94l-2.39-.96a.48.48 0 0 0-.59.22L2.74 8.87a.48.48 0 0 0 .12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.5.5 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32a.5.5 0 0 0-.12-.61zM12 15.6A3.6 3.6 0 1 1 12 8.4a3.6 3.6 0 0 1 0 7.2z",
  grid: "M3 3v8h8V3zm6 6H5V5h4zm-6 4v8h8v-8zm6 6H5v-4h4zm4-16v8h8V3zm6 6h-4V5h4zm-6 4v8h8v-8zm6 6h-4v-4h4z",
  list: "M3 13h2v-2H3zm0 4h2v-2H3zm0-8h2V7H3zm4 4h14v-2H7zm0 4h14v-2H7zM7 7v2h14V7z",
  refresh: "M17.65 6.35A7.96 7.96 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z",
  sortup: "M3 18h6v-2H3zM3 6v2h18V6zm0 7h12v-2H3z", sortdown: "M3 18h18v-2H3zM3 6v2h6V6zm0 7h12v-2H3z",
  more: "M12 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm0 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm0 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  close: "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
  check: "M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z", prev: "M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z", next: "M10 6 8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z",
  copy: "M16 1H4a2 2 0 0 0-2 2v14h2V3h12zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11z",
  move: "M10 9h4V6h3l-5-5-5 5h3zm-1 1H6V7l-5 5 5 5v-3h3zm14 2-5-5v3h-3v4h3v3zm-9 3h-4v3H7l5 5 5-5h-3z",
  rename: "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75z",
  history: "M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6a7 7 0 1 1 2.05 4.95l-1.42 1.42A9 9 0 1 0 13 3zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8z",
  restore: "M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6a7 7 0 1 1 2.05 4.95l-1.42 1.42A9 9 0 1 0 13 3z",
  open: "M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3z",
  image: "M21 19V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5z",
  video: "M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11z",
  audio: "M12 3v10.55A4 4 0 1 0 14 17V7h4V3z", pdf: "M20 2H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zM4 6H2v14a2 2 0 0 0 2 2h14v-2H4z",
  doc: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zm2 16H8v-2h8zm0-4H8v-2h8zm-3-5V3.5L18.5 9z",
  code: "M9.4 16.6 4.8 12l4.6-4.6L8 6l-6 6 6 6zm5.2 0 4.6-4.6-4.6-4.6L16 6l6 6-6 6z",
  archive: "M20.54 5.23l-1.39-1.68A1.5 1.5 0 0 0 18 3H6c-.47 0-.88.21-1.15.55L3.46 5.23A2 2 0 0 0 3 6.5V19a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6.5c0-.48-.17-.93-.46-1.27zM12 17.5 6.5 12H10v-2h4v2h3.5zM5.12 5l.81-1h12l.94 1z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
  empty: "M20 6h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2z",
  info: "M11 7h2v2h-2zm0 4h2v6h-2zm1-9a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16z",
  play: "M8 5v14l11-7z",
};
const svg = (n) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${P[n] || P.file}"/></svg>`;
function paintIcons(root = document) { $$("[data-i]", root).forEach((e) => { e.innerHTML = svg(e.dataset.i); }); }
const BTN_ICONS = { btnMenu: "menu", btnTheme: "theme", btnSettings: "gear", btnSortDir: "sortdown", vGrid: "grid", vList: "list", btnRefresh: "refresh", btnInfo: "info", pvClose: "close", pvPrev: "prev", pvNext: "next", pvShare: "link", pvDownload: "download" };
for (const [id, n] of Object.entries(BTN_ICONS)) $("#" + id).innerHTML = svg(n);
$(".s-ico").innerHTML = svg("search");
paintIcons();

/* ---------- state & prefs ---------- */
const S = { token: null, role: null, root: "main", path: "", view: "files", items: [], sel: new Set(), last: null, sort: "name", dir: 1, mode: "grid",
            ws: null, wsTimer: null, tokenMode: false, cut: null, starred: new Set(), query: "", kind: "", reqId: 0 };
const PREF_DEFAULTS = { confirmDelete: true, iso: false, thumbs: true, parallel: 3, mode: "grid", sort: "name", dir: 1, theme: "" };
function loadPrefs() { try { return { ...PREF_DEFAULTS, ...JSON.parse(localStorage.getItem("sl_prefs") || "{}") }; } catch (e) { return { ...PREF_DEFAULTS }; } }
function savePrefs() { try { localStorage.setItem("sl_prefs", JSON.stringify(S.prefs)); } catch (e) { /* ignore */ } }
S.prefs = loadPrefs(); S.mode = S.prefs.mode; S.sort = S.prefs.sort; S.dir = S.prefs.dir;
function applyTheme() { const t = S.prefs.theme; if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }
applyTheme();
$("#btnTheme").onclick = () => {
  const dark = document.documentElement.dataset.theme === "dark" || (!S.prefs.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  S.prefs.theme = dark ? "light" : "dark"; savePrefs(); applyTheme();
};

const fmtSize = (n) => { if (!n) return "—"; const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return n.toFixed(i ? 1 : 0) + " " + u[i]; };
const sz = (n) => (n ? fmtSize(n) : "0 B");
function fmtDate(t) {
  const d = new Date(t * 1000);
  if (S.prefs.iso) return d.toISOString().replace("T", " ").slice(0, 16);
  const now = new Date(), same = d.toDateString() === now.toDateString();
  return same ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : d.toLocaleDateString([], { year: d.getFullYear() === now.getFullYear() ? undefined : "numeric", month: "short", day: "numeric" });
}
function toast(msg, err, action) {
  const t = h("div", { class: "toast" + (err ? " err" : "") }, msg);
  if (action) t.append(h("button", { onclick: () => { action.fn(); t.remove(); } }, action.label));
  $("#toasts").append(t); setTimeout(() => t.remove(), action ? 8000 : 4000);
}
const closeDialogs = () => $$("dialog[open]").forEach((d) => d.close());
$$("[data-close]").forEach((b) => (b.onclick = () => b.closest("dialog").close()));
$$("dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d && !d.classList.contains("sticky")) d.close(); }));

/* ---------- file types ---------- */
const EXT = {
  image: "png jpg jpeg gif webp bmp svg ico avif heic tiff", video: "mp4 mkv mov avi webm m4v wmv", audio: "mp3 wav flac ogg m4a aac opus",
  pdf: "pdf", doc: "doc docx odt rtf txt md xls xlsx ods csv ppt pptx odp", code: "py js ts jsx tsx json html css c cpp h java kt go rs sh bat ps1 yml yaml toml ini xml sql php rb lua",
  archive: "zip rar 7z tar gz bz2 xz iso",
};
const extOf = (n) => (n.includes(".") ? n.split(".").pop().toLowerCase() : "");
function kindOf(it) {
  if (it.type === "dir") return "dir";
  const e = extOf(it.name);
  for (const [k, v] of Object.entries(EXT)) if (v.split(" ").includes(e)) return k;
  return "file";
}
const PREVIEWABLE = new Set(["image", "video", "audio", "pdf"]);
const TEXTY = (it) => { const e = extOf(it.name); return !e || EXT.code.split(" ").includes(e) || ["txt", "md", "csv", "log", "cfg", "conf", "env", "gitignore"].includes(e); };
const fileIcon = (it) => { const k = kindOf(it); return Object.assign(h("span", { class: "ico fi t-" + k }), { innerHTML: svg(k === "dir" ? "folder" : k) }); };

/* ---------- dialogs ---------- */
function ask(o) {
  return new Promise((resolve) => {
    const d = $("#dlgAsk"), inp = $("#askInput");
    $("#askTitle").textContent = o.title || ""; $("#askMsg").textContent = o.message || ""; $("#askMsg").classList.toggle("hidden", !o.message);
    $("#askLabel").classList.toggle("hidden", !o.input); $("#askErr").textContent = "";
    if (o.input) { $("#askLabelText").textContent = o.input.label || ""; inp.value = o.input.value || ""; inp.type = o.input.type || "text"; }
    const ok = $("#askOk"); ok.textContent = o.ok || "OK"; ok.classList.toggle("danger", !!o.danger);
    let result = null; const ex = $("#askExtra");
    ex.classList.toggle("hidden", !o.extra); ex.textContent = o.extra || ""; ex.onclick = () => { result = false; d.close(); };
    d.onclose = () => resolve(result);
    $("#askCancel").onclick = () => d.close();
    $("#askForm").onsubmit = (ev) => {
      ev.preventDefault();
      if (o.input) { const v = inp.value.trim(); const bad = o.input.validate ? o.input.validate(v) : (v ? "" : "Please enter a value."); if (bad) { $("#askErr").textContent = bad; return; } result = v; }
      else result = true;
      d.close();
    };
    d.showModal(); if (o.input) { inp.focus(); if (o.input.select !== false) { const dot = inp.value.lastIndexOf("."); o.input.selectName && dot > 0 ? inp.setSelectionRange(0, dot) : inp.select(); } } else ok.focus();
  });
}
const confirmBox = async (title, message, ok = "Confirm", danger = true) => !!(await ask({ title, message, ok, danger }));
const nameCheck = (v) => (!v ? "Please enter a name." : /[\\/:*?"<>|]/.test(v) || v === "." || v === ".." ? "A name cannot contain \\ / : * ? \" < > |" : "");
const promptName = (title, value = "", ok = "OK", selectName = false) => ask({ title, ok, input: { label: "Name", value, validate: nameCheck, selectName } });

/* ---------- auth ---------- */
function saveToken(t, remember) { localStorage.removeItem("sl_token"); sessionStorage.removeItem("sl_token"); (remember ? localStorage : sessionStorage).setItem("sl_token", t); }
function logout() {
  closeDialogs(); localStorage.removeItem("sl_token"); sessionStorage.removeItem("sl_token"); S.token = null;
  if (S.ws) { S.ws.onclose = null; S.ws.close(); S.ws = null; }
  clearTimeout(S.wsTimer); $("#app").classList.add("hidden"); $("#login").classList.remove("hidden");
}
async function api(method, url, body, raw) {
  const opt = { method, headers: { Authorization: "Bearer " + S.token } };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (r.status === 401) { logout(); throw new Error("Session expired"); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) { /* ignore */ } throw new Error(m); }
  return raw ? r : r.json();
}
async function authUrl(p, o) { const { ticket } = await api("GET", "/api/ticket"); return `${p}?${qs({ ...o, ticket })}`; }
async function saveVia(url, name) { const a = h("a", { href: url, download: name || "" }); document.body.append(a); a.click(); a.remove(); }
const fileUrl = (p, kind = "preview") => `/api/${kind}?${qs({ root: S.root, path: p })}`;
async function blobUrl(url) { const r = await api("GET", url, undefined, true); return URL.createObjectURL(await r.blob()); }

$("#toggleMode").onclick = () => {
  S.tokenMode = !S.tokenMode; $("#credFields").classList.toggle("hidden", S.tokenMode); $("#tokenField").classList.toggle("hidden", !S.tokenMode);
  $("#toggleMode").textContent = S.tokenMode ? "Use username & password" : "Use a device token instead";
};
$("#loginForm").onsubmit = async (ev) => {
  ev.preventDefault(); $("#loginErr").textContent = "";
  try {
    let token;
    if (S.tokenMode) token = $("#lToken").value.trim();
    else {
      const body = { username: $("#lUser").value, password: $("#lPass").value };
      for (;;) {
        const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const d = await r.json().catch(() => ({}));
        if (r.ok) { token = d.token; break; }
        if (r.status === 401 && String(d.detail || "").startsWith("mfa_required")) {
          const methods = String(d.detail).split(":")[1] || "";
          if (/sms|email/.test(methods)) fetch("/api/auth/mfa/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: body.username, password: body.password }) }).catch(() => {});
          const code = await ask({ title: "Two-step verification", message: "Enter the code from your authenticator, SMS/e-mail, or a recovery code.", ok: "Verify", input: { label: "Code", validate: (v) => (v ? "" : "Enter the code.") } });
          if (!code) throw new Error("Sign-in cancelled"); body.code = code; continue;
        }
        throw new Error(d.detail || "Login failed");
      }
    }
    S.token = token; await api("GET", "/api/me"); saveToken(token, $("#lRemember").checked); $("#lPass").value = ""; await start();
  } catch (e) { S.token = null; $("#loginErr").textContent = e.message; }
};
$("#logout").onclick = logout;

async function start() {
  const me = await api("GET", "/api/me"); S.role = me.role; S.me = me;
  $("#who").textContent = (me.name || "?").slice(0, 1);
  $("#adminNav").classList.toggle("hidden", me.role !== "admin");
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  const ri = (await api("GET", "/api/roots")).items, sel = $("#rootSel");
  S.rootInfo = Object.fromEntries(ri.map((r) => [r.id, r])); S.home = (ri.find((r) => r.kind !== "shared") || ri[0] || { id: "main" }).id;
  const own = ri.filter((r) => r.kind !== "shared");
  sel.replaceChildren(...own.map((r) => h("option", { value: r.id }, r.label))); sel.classList.toggle("hidden", own.length < 2);
  $("#withmeNav").classList.toggle("hidden", me.role !== "member");
  if (!S.rootInfo[S.root]) S.root = S.home; sel.value = own.some((r) => r.id === S.root) ? S.root : S.home;
  S.path = ""; syncViewButtons(); await go("files"); connectWS(); loadUsage();
}
$("#rootSel").onchange = (e) => { S.root = e.target.value; S.home = S.root; S.path = ""; go("files"); loadUsage(); };
async function loadUsage() {
  try {
    const d = await api("GET", "/api/usage?" + qs({ root: S.root })), total = d.quota || (d.disk && d.disk.total) || 0;
    $("#usage").textContent = d.quota ? `${sz(d.used)} of ${sz(d.quota)} used` : `${sz(d.used)} used`;
    $("#usageBar").style.width = total ? Math.min(100, (d.used / total) * 100) + "%" : "0%";
  } catch (e) { /* ignore */ }
}

/* ---------- navigation & listing ---------- */
const TITLES = { withme: "Shared with me", recent: "Recent", starred: "Starred", shared: "Shared links", trash: "Trash", search: "Search results" };
async function go(view, path) {
  S.view = view; if (path != null) S.path = path; S.sel.clear(); S.last = null;
  $$("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.nav === (view === "search" ? "files" : view)));
  const adm = view === "admin"; $("#viewFiles").classList.toggle("hidden", adm); $("#viewAdmin").classList.toggle("hidden", !adm);
  $("#side").classList.remove("open"); $("#scrim").classList.add("hidden");
  if (adm) { loadAdmin(); return; }
  if (view !== "search") { $("#search").value = ""; S.query = ""; }
  await refresh();
}
$$("#nav button").forEach((b) => (b.onclick = () => { if (b.dataset.nav === "files") { S.path = ""; if (S.root.startsWith("s:")) { S.root = S.home; $("#rootSel").value = S.home; loadUsage(); } } go(b.dataset.nav); }));
let refreshT = null;
const refreshSoon = () => { clearTimeout(refreshT); refreshT = setTimeout(() => { if (!document.querySelector("dialog[open]") && S.view !== "admin") refresh(true); }, 400); };
async function refresh(keepSel) {
  const id = ++S.reqId;
  try {
    let items = [], banner = "";
    if (S.starred.size === 0 || S.view === "files") { try { S.starred = new Set((await api("GET", "/api/stars")).items.filter((s) => s.root === S.root).map((s) => s.path)); } catch (e) { /* ignore */ } }
    if (S.view === "files") items = (await api("GET", "/api/files?" + qs({ root: S.root, path: S.path }))).items.map((i) => ({ ...i, path: joinPath(S.path, i.name) }));
    else if (S.view === "withme") {
      const d = await api("GET", "/api/grants");
      items = d.received.map((g) => ({ name: g.name, type: "dir", size: 0, mtime: g.created, path: "", shareRoot: "s:" + g.id, tid: "g" + g.id, sub: `from ${g.owner} · ${g.writable ? "can edit" : "view only"}` }));
      banner = items.length ? "" : "";
    } else if (S.view === "recent") items = (await api("GET", "/api/recent?" + qs({ root: S.root }))).items;
    else if (S.view === "starred") items = (await api("GET", "/api/stars")).items.filter((s) => s.root === S.root);
    else if (S.view === "search") items = (await api("GET", "/api/search?" + qs({ root: S.root, q: S.query, kind: S.kind }))).items;
    else if (S.view === "trash") {
      const d = await api("GET", "/api/trash?" + qs({ root: S.root }));
      items = d.items.map((t) => ({ name: t.name, type: t.type, size: t.size, mtime: t.deleted, path: t.path, tid: t.id }));
      banner = d.days > 0 ? `Items in the trash are deleted forever after ${d.days} days. ${items.length ? sz(d.total) + " in trash." : ""}` : "Trash is turned off: deleted items are removed immediately.";
    } else if (S.view === "shared") {
      const d = await api("GET", "/api/shares?" + qs({ root: S.root }));
      items = d.items.map((s) => ({ name: baseName(s.path), path: s.path, type: "file", size: 0, mtime: s.created, share: s }));
      await Promise.all(items.map(async (it) => { try { const p = await api("GET", "/api/files?" + qs({ root: S.root, path: parentOf(it.path) })); const f = p.items.find((x) => x.name === it.name); if (f) { it.type = f.type; it.size = f.size; } } catch (e) { /* gone */ } }));
    }
    if (id !== S.reqId) return;
    S.items = items; const b = $("#banner"); b.textContent = banner; b.classList.toggle("hidden", !banner);
    if (!keepSel) S.sel.clear(); else S.sel = new Set([...S.sel].filter((p) => items.some((i) => selKey(i) === p)));
    render();
  } catch (e) { if (id === S.reqId) toast(e.message, true); }
}
const selKey = (it) => it.tid || it.path;
function sorted() {
  const a = S.items.slice(), k = S.sort, d = S.dir;
  a.sort((x, y) => {
    if (S.view === "files" || S.view === "search") if ((x.type === "dir") !== (y.type === "dir")) return x.type === "dir" ? -1 : 1;
    const v = k === "name" ? x.name.localeCompare(y.name, undefined, { numeric: true, sensitivity: "base" }) : k === "size" ? x.size - y.size : x.mtime - y.mtime;
    return v * d;
  });
  return a;
}
function syncViewButtons() {
  $("#vGrid").classList.toggle("on", S.mode === "grid"); $("#vList").classList.toggle("on", S.mode === "list");
  $("#sortSel").value = S.sort; $("#btnSortDir").innerHTML = svg(S.dir > 0 ? "sortdown" : "sortup");
}
$("#vGrid").onclick = () => { S.mode = S.prefs.mode = "grid"; savePrefs(); syncViewButtons(); render(); };
$("#vList").onclick = () => { S.mode = S.prefs.mode = "list"; savePrefs(); syncViewButtons(); render(); };
$("#sortSel").onchange = (e) => { S.sort = S.prefs.sort = e.target.value; savePrefs(); render(); };
$("#btnSortDir").onclick = () => { S.dir = S.prefs.dir = -S.dir; savePrefs(); syncViewButtons(); render(); };
$("#btnRefresh").onclick = () => refresh();
$("#btnMenu").onclick = () => { $("#side").classList.add("open"); $("#scrim").classList.remove("hidden"); $("#scrim").classList.add("show"); };
$("#scrim").onclick = () => { $("#side").classList.remove("open"); $("#scrim").classList.add("hidden"); $("#scrim").classList.remove("show"); };

function renderCrumbs() {
  const c = $("#crumbs"); c.replaceChildren();
  if (S.view !== "files") { c.append(h("a", { class: "cur" }, S.view === "search" ? `Results for “${S.query || S.kind}”` : TITLES[S.view])); return; }
  const parts = S.path ? S.path.split("/") : [], mk = (label, p, cur) => {
    const a = h("a", { href: "#", class: cur ? "cur" : "", onclick: (e) => { e.preventDefault(); if (!cur) go("files", p); } }, label);
    a.ondragover = (e) => { if (S.drag) { e.preventDefault(); a.classList.add("dragover"); } }; a.ondragleave = () => a.classList.remove("dragover");
    a.ondrop = (e) => { a.classList.remove("dragover"); if (S.drag) { e.preventDefault(); e.stopPropagation(); moveInto(p); } }; return a;
  };
  const ri = S.rootInfo && S.rootInfo[S.root];
  if (ri && ri.kind === "shared") c.append(h("a", { href: "#", onclick: (e) => { e.preventDefault(); go("withme"); } }, "Shared with me"), h("span", {}, "›"));
  c.append(mk(ri && ri.kind === "shared" ? ri.label.replace(/ \(from .*\)$/, "") : ri && ri.kind === "server" && S.role === "admin" && Object.keys(S.rootInfo).length > 1 ? ri.label : "My files", "", !parts.length));
  parts.forEach((n, i) => { c.append(h("span", {}, "›"), mk(n, parts.slice(0, i + 1).join("/"), i === parts.length - 1)); });
}
function thumbEl(it) {
  const k = kindOf(it), box = h("div", { class: "thumb" });
  if (k === "dir") { box.append(Object.assign(h("span", { class: "ico big t-dir" }), { innerHTML: svg("folder") })); return box; }
  box.append(Object.assign(h("span", { class: "ico big t-" + k }), { innerHTML: svg(k) }));
  if (k === "image" && S.prefs.thumbs && !it.tid && S.view !== "trash" && it.size < 80e6) {
    const key = S.root + "|" + it.path + "|" + it.mtime;
    const put = (u) => { const im = h("img", { alt: "", src: u }); im.onload = () => box.replaceChildren(im); };
    if (THUMBS.has(key)) put(THUMBS.get(key));
    else thumbQueue(() => blobUrl("/api/thumb?" + qs({ root: S.root, path: it.path })).then((u) => { THUMBS.set(key, u); put(u); }).catch(() => {}));
  }
  return box;
}
const THUMBS = new Map(); let thumbActive = 0; const thumbWait = [];
function thumbQueue(fn) { thumbWait.push(fn); thumbPump(); }
function thumbPump() { while (thumbActive < 4 && thumbWait.length) { const f = thumbWait.shift(); thumbActive++; Promise.resolve(f()).finally(() => { thumbActive--; thumbPump(); }); } }
function sortHead(key, label, cls) {
  const on = S.sort === key;
  return h("span", { class: (cls || "") + " sorth" + (on ? " on" : ""), onclick: () => { if (S.sort === key) S.dir = S.prefs.dir = -S.dir; else { S.sort = S.prefs.sort = key; S.dir = S.prefs.dir = 1; } savePrefs(); render(); } }, label, on ? (S.dir > 0 ? " ↑" : " ↓") : "");
}
function render() {
  syncViewButtons(); renderCrumbs();
  const wrap = $("#items"), list = sorted(); wrap.className = "items " + S.mode + (S.sel.size ? " selecting" : "");
  wrap.replaceChildren();
  const showSec = S.view === "files" && S.mode === "grid" && list.some((i) => i.type === "dir") && list.some((i) => i.type !== "dir");
  if (S.mode === "list") wrap.append(h("div", { class: "row-item head" }, h("span"), sortHead("name", "Name"), sortHead("mtime", S.view === "trash" ? "Deleted" : "Modified", "c-mod"), sortHead("size", "Size", "r c-size"), h("span")));
  let lastType = null;
  for (const it of list) {
    if (showSec && it.type !== lastType) { wrap.append(h("div", { class: "sec" }, it.type === "dir" ? "Folders" : "Files")); lastType = it.type; }
    wrap.append(S.mode === "grid" ? tile(it) : row(it));
  }
  const empty = $("#empty"), none = !list.length;
  empty.classList.toggle("hidden", !none); wrap.classList.toggle("hidden", none);
  if (none) {
    const msg = { files: ["This folder is empty", "Drop files here or use New to upload"], recent: ["Nothing yet", "Files you add or change show up here"], starred: ["No starred items", "Star important files to find them quickly"],
      withme: ["Nothing shared with you yet", "Folders other people share with you appear here"], shared: ["No shared links", "Share a file to create a link anyone can open"], trash: ["Trash is empty", ""], search: ["No matches", "Try another search"] }[S.view];
    empty.replaceChildren(Object.assign(h("div", { class: "art" }), { innerHTML: svg(S.view === "trash" ? "trash" : S.view === "starred" ? "star" : S.view === "shared" ? "link" : "empty") }), h("h2", {}, msg[0]), h("p", {}, msg[1]), S.view === "files" && canWrite() ? h("button", { class: "btn primary", onclick: () => $("#fileInput").click() }, "Upload files") : null);
  }
  renderSelbar(); renderInfo();
}
function attach(el, it) {
  el.dataset.k = selKey(it);
  el.draggable = S.view === "files";
  el.addEventListener("click", (e) => clickItem(e, it));
  el.addEventListener("dblclick", () => openItem(it));
  el.addEventListener("contextmenu", (e) => { e.preventDefault(); if (!S.sel.has(selKey(it))) { S.sel = new Set([selKey(it)]); S.last = selKey(it); paintSel(); } showCtx(e.clientX, e.clientY, it); });
  el.addEventListener("dragstart", (e) => { if (!S.sel.has(selKey(it))) { S.sel = new Set([selKey(it)]); paintSel(); } S.drag = [...S.sel]; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", "sl"); });
  el.addEventListener("dragend", () => { S.drag = null; });
  if (it.type === "dir" && S.view === "files") {
    el.addEventListener("dragover", (e) => { if (S.drag && !S.drag.includes(it.path)) { e.preventDefault(); el.classList.add("dragover"); } });
    el.addEventListener("dragleave", () => el.classList.remove("dragover"));
    el.addEventListener("drop", (e) => { el.classList.remove("dragover"); if (S.drag && !S.drag.includes(it.path)) { e.preventDefault(); e.stopPropagation(); moveInto(it.path); } });
  }
  return el;
}
const chkEl = (it) => { const c = h("span", { class: "chk", onclick: (e) => { e.stopPropagation(); toggleSel(it); } }); c.innerHTML = svg("check"); return c; };
const moreBtn = (it) => { const b = h("button", { class: "icon-btn more", title: "More", onclick: (e) => { e.stopPropagation(); if (!S.sel.has(selKey(it))) { S.sel = new Set([selKey(it)]); paintSel(); } const r = e.currentTarget.getBoundingClientRect(); showCtx(r.left, r.bottom, it); } }); b.innerHTML = svg("more"); return b; };
const starMark = (it) => S.starred.has(it.path) && it.type !== undefined && !it.tid ? Object.assign(h("span", { class: "star-mark" }), { innerHTML: svg("star") }) : null;
function tile(it) {
  const sub = it.sub || (S.view === "files" ? "" : (it.path.includes("/") ? parentOf(it.path) : "My files"));
  const t = h("div", { class: "tile " + (it.type === "dir" ? "dir " : "") + (S.sel.has(selKey(it)) ? "sel" : "") },
    chkEl(it), thumbEl(it), h("div", { class: "meta" }, fileIcon(it), h("span", { class: "nm", title: it.name }, it.name, sub ? h("span", { class: "sub" }, sub) : null), moreBtn(it)));
  const st = starMark(it); if (st) t.append(st);
  return attach(t, it);
}
function row(it) {
  const r = h("div", { class: "row-item " + (S.sel.has(selKey(it)) ? "sel" : "") }, chkEl(it),
    h("span", { class: "nm", title: it.path }, fileIcon(it), it.name, S.starred.has(it.path) ? Object.assign(h("span", { class: "ico", style: "width:16px;height:16px;color:#f9ab00" }), { innerHTML: svg("star") }) : null,
      it.sub ? h("span", { class: "pathnote" }, it.sub) : S.view !== "files" && it.path.includes("/") ? h("span", { class: "pathnote" }, parentOf(it.path)) : null),
    h("span", { class: "c-mod muted" }, fmtDate(it.mtime)), h("span", { class: "r c-size muted" }, it.type === "dir" ? "—" : fmtSize(it.size)), moreBtn(it));
  return attach(r, it);
}

/* ---------- selection ---------- */
function paintSel() { $$("#items [data-k]").forEach((e) => e.classList.toggle("sel", S.sel.has(e.dataset.k))); $("#items").classList.toggle("selecting", S.sel.size > 0); renderSelbar(); renderInfo(); }
function toggleSel(it) { const k = selKey(it); S.sel.has(k) ? S.sel.delete(k) : S.sel.add(k); S.last = k; paintSel(); }
function clickItem(e, it) {
  const k = selKey(it);
  if (e.shiftKey && S.last) {
    const keys = sorted().map(selKey), a = keys.indexOf(S.last), b = keys.indexOf(k);
    if (a >= 0 && b >= 0) { S.sel = new Set(keys.slice(Math.min(a, b), Math.max(a, b) + 1)); paintSel(); return; }
  }
  if (e.ctrlKey || e.metaKey || S.sel.size && matchMedia("(pointer:coarse)").matches) { toggleSel(it); return; }
  S.sel = new Set([k]); S.last = k; paintSel();
  if (matchMedia("(pointer:coarse)").matches) openItem(it);
}
$("#items").addEventListener("click", (e) => { if (e.target === $("#items")) { S.sel.clear(); paintSel(); } });
const selItems = () => S.items.filter((i) => S.sel.has(selKey(i)));
function renderSelbar() {
  const bar = $("#selbar"), its = selItems(); bar.classList.toggle("hidden", !its.length); bar.replaceChildren();
  if (!its.length) return;
  const btn = (n, title, fn, cls) => { const b = h("button", { class: "icon-btn " + (cls || ""), title, onclick: fn }); b.innerHTML = svg(n); return b; };
  bar.append(btn("close", "Clear selection", () => { S.sel.clear(); paintSel(); }), h("span", { class: "count" }, its.length + " selected"));
  if (S.view === "withme") bar.append(btn("open", "Open", () => openItem(its[0])));
  else if (S.view === "trash") bar.append(btn("restore", "Restore", () => trashRestore(its)), btn("trash", "Delete forever", () => trashPurge(its)));
  else if (S.view === "shared") bar.append(btn("link", "Manage link", () => shareDialog(its[0])), btn("trash", "Stop sharing", async () => { for (const i of its) await api("DELETE", "/api/shares/" + i.share.token); toast("Stopped sharing"); refresh(); }));
  else {
    bar.append(btn("download", "Download", () => its.forEach(download)));
    if (its.length === 1 && !S.me.read_only) bar.append(btn("link", "Share", () => shareDialog(its[0])));
    bar.append(btn("star", "Star", () => starSel(its, true)), btn("copy", "Copy to", () => pickDest(its, "copy")));
    if (canWrite()) bar.append(btn("move", "Move to", () => pickDest(its, "move")), btn("trash", "Move to trash", () => trashSel(its)));
  }
}
const canWrite = () => !S.me.read_only && !(S.rootInfo && S.rootInfo[S.root] && !S.rootInfo[S.root].writable) && S.view !== "withme";

/* ---------- details panel ---------- */
$("#btnInfo").onclick = () => { S.prefs.info = !S.prefs.info; savePrefs(); renderInfo(); };
function renderInfo() {
  const p = $("#info"), show = !!S.prefs.info && S.view !== "admin"; p.classList.toggle("hidden", !show); $("#btnInfo").classList.toggle("on", show);
  if (!show) return;
  const its = selItems(), row = (k, v) => v == null || v === "" ? null : h("div", { class: "kvr" }, h("span", {}, k), h("b", {}, v));
  if (its.length === 1) {
    const it = its[0], kind = kindOf(it), btn = (n, t, fn) => h("button", { class: "btn tonal small", onclick: fn }, t);
    p.replaceChildren(thumbEl(it), h("h3", { class: "iname" }, it.name),
      row("Type", it.type === "dir" ? "Folder" : (extOf(it.name) || "file").toUpperCase() + " " + kind), row("Size", it.type === "dir" ? "" : fmtSize(it.size) + " (" + it.size.toLocaleString() + " bytes)"),
      row("Modified", it.mtime ? new Date(it.mtime * 1000).toLocaleString() : ""), row("Location", "My files" + (parentOf(it.path) ? "/" + parentOf(it.path) : "")), row("Starred", S.starred.has(it.path) ? "Yes" : "No"),
      S.view === "trash" ? null : h("div", { class: "row wrap" }, btn("open", "Open", () => openItem(it)), btn("link", "Share", () => shareDialog(it)),
        it.type === "file" ? btn("history", "Versions", () => versionsDialog(it)) : null, btn("download", "Download", () => download(it))));
  } else if (its.length > 1) {
    p.replaceChildren(h("h3", {}, its.length + " items selected"), row("Total size", fmtSize(its.reduce((a, i) => a + (i.type === "dir" ? 0 : i.size), 0))));
  } else {
    const dirs = S.items.filter((i) => i.type === "dir").length, files = S.items.length - dirs;
    p.replaceChildren(h("h3", {}, S.view === "files" ? (S.path ? baseName(S.path) : "My files") : TITLES[S.view] || "Files"), row("Folders", dirs), row("Files", files),
      row("Size of files", fmtSize(S.items.reduce((a, i) => a + (i.type === "dir" ? 0 : i.size), 0))), h("p", { class: "muted small" }, "Select an item to see its details."));
  }
}

/* ---------- context menu ---------- */
function showCtx(x, y, it) {
  const m = $("#ctx"), its = selItems().length ? selItems() : [it], one = its.length === 1, w = canWrite(); m.replaceChildren();
  const add = (n, label, fn, cls) => m.append(h("button", { class: cls || "", onclick: () => { m.classList.add("hidden"); fn(); } }, h("span", { class: "ico" }), label));
  const hr = () => m.append(h("hr"));
  const addI = (n, label, fn, cls) => { add(n, label, fn, cls); m.lastChild.firstChild.innerHTML = svg(n); };
  if (S.view === "withme") { addI("open", "Open", () => openItem(it)); addI("trash", "Leave this share", async () => { try { await api("DELETE", "/api/grants/" + it.shareRoot.slice(2)); refresh(); } catch (e) { toast(e.message, true); } }, "danger"); }
  else if (S.view === "trash") { addI("restore", "Restore", () => trashRestore(its)); addI("trash", "Delete forever", () => trashPurge(its), "danger"); }
  else if (S.view === "shared") { addI("link", "Manage link", () => shareDialog(its[0])); addI("open", "Open", () => openItem(its[0])); }
  else {
    if (one) addI("open", it.type === "dir" ? "Open" : "Preview / open", () => openItem(it));
    if (one && it.type === "file" && TEXTY(it)) addI("edit", w ? "Edit as text" : "View as text", () => editText(it));
    addI("download", it.type === "dir" && one ? "Download as zip" : "Download", () => its.forEach(download));
    if (one) addI("link", "Share…", () => shareDialog(it));
    hr();
    const starred = its.every((i) => S.starred.has(i.path)); addI(starred ? "starout" : "star", starred ? "Remove star" : "Add star", () => starSel(its, !starred));
    if (one && it.type === "file") addI("history", "Version history", () => versionsDialog(it));
    hr();
    if (w && one) addI("rename", "Rename", () => renameItem(it));
    addI("copy", "Make a copy / copy to…", () => pickDest(its, "copy"));
    if (w) { addI("move", "Move to…", () => pickDest(its, "move")); hr(); addI("trash", "Move to trash", () => trashSel(its), "danger"); }
    if (S.view !== "files" && one) { hr(); addI("folder", "Show in folder", () => { go("files", it.type === "dir" ? it.path : parentOf(it.path)); }); }
  }
  m.classList.remove("hidden"); m.style.left = m.style.top = "0px";
  const r = m.getBoundingClientRect(); m.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + "px"; m.style.top = Math.max(8, Math.min(y, innerHeight - r.height - 8)) + "px";
}
document.addEventListener("click", (e) => { if (!e.target.closest("#ctx")) $("#ctx").classList.add("hidden"); if (!e.target.closest(".newwrap")) $("#newMenu").classList.add("hidden"); });
addEventListener("blur", () => $("#ctx").classList.add("hidden"));

/* ---------- actions ---------- */
async function download(it) { try { saveVia(await authUrl("/api/download", { root: S.root, path: it.path }), it.name); } catch (e) { toast(e.message, true); } }
async function openItem(it) {
  if (S.view === "trash") return;
  if (it.shareRoot) { S.root = it.shareRoot; S.path = ""; S.starred = new Set(); await go("files", ""); loadUsage(); return; }
  if (it.type === "dir") return go("files", it.path);
  const k = kindOf(it);
  if (PREVIEWABLE.has(k)) return preview(it);
  if (TEXTY(it) && it.size <= 2 * 1024 * 1024) return editText(it);
  download(it);
}
async function renameItem(it) {
  const n = await promptName("Rename", it.name, "Rename", true); if (!n || n === it.name) return;
  try { await api("POST", "/api/move", { root: S.root, src: it.path, dst: joinPath(parentOf(it.path), n) }); toast("Renamed"); refresh(); } catch (e) { toast(e.message, true); }
}
async function trashSel(its) {
  if (S.prefs.confirmDelete && !(await confirmBox("Move to trash?", its.length === 1 ? `“${its[0].name}” will be moved to the trash.` : `${its.length} items will be moved to the trash.`, "Move to trash"))) return;
  try { const d = await api("POST", "/api/batch", { root: S.root, op: "delete", paths: its.map((i) => i.path), dest: "" }); if (d.errors.length) toast(d.errors[0].error, true); else toast(its.length > 1 ? `${its.length} items moved to trash` : "Moved to trash", false, { label: "Trash", fn: () => go("trash") }); S.sel.clear(); refresh(); loadUsage(); } catch (e) { toast(e.message, true); }
}
async function trashRestore(its) { try { for (const i of its) await api("POST", "/api/trash/restore", { root: S.root, id: i.tid }); toast("Restored"); refresh(); loadUsage(); } catch (e) { toast(e.message, true); } }
async function trashPurge(its) {
  if (!(await confirmBox("Delete forever?", "This cannot be undone.", "Delete forever"))) return;
  try { for (const i of its) await api("DELETE", "/api/trash?" + qs({ root: S.root, id: i.tid })); refresh(); loadUsage(); } catch (e) { toast(e.message, true); }
}
async function starSel(its, on) {
  try { for (const i of its) { if (on) await api("PUT", "/api/stars", { root: S.root, path: i.path }); else await api("DELETE", "/api/stars?" + qs({ root: S.root, path: i.path })); } S.starred = new Set((await api("GET", "/api/stars")).items.filter((s) => s.root === S.root).map((s) => s.path)); if (S.view === "starred") refresh(); else render(); } catch (e) { toast(e.message, true); }
}
async function moveInto(dest) {
  const paths = (S.drag || []).filter((p) => parentOf(p) !== dest && p !== dest); S.drag = null; if (!paths.length) return;
  try { const d = await api("POST", "/api/batch", { root: S.root, op: "move", paths, dest }); if (d.errors.length) toast(d.errors[0].error, true); else toast("Moved"); S.sel.clear(); refresh(); } catch (e) { toast(e.message, true); }
}
$("#ctx").addEventListener("contextmenu", (e) => e.preventDefault());
$("#viewFiles").addEventListener("contextmenu", (e) => {
  if (e.target.closest("[data-k]") || S.view !== "files" || !canWrite()) return; e.preventDefault(); S.sel.clear(); paintSel();
  const m = $("#ctx"); m.replaceChildren();
  for (const [n, label, act] of [["folderplus", "New folder", "newFolder"], ["edit", "New text file", "newText"], ["upload", "Upload files", "uploadFiles"], ["folder", "Upload folder", "uploadDir"]])
    { const b = h("button", { onclick: () => { m.classList.add("hidden"); $(`#newMenu [data-act=${act}]`).click(); } }, h("span", { class: "ico" }), label); b.firstChild.innerHTML = svg(n); m.append(b); }
  m.classList.remove("hidden"); m.style.left = Math.min(e.clientX, innerWidth - 240) + "px"; m.style.top = Math.min(e.clientY, innerHeight - 200) + "px";
});

/* ---------- folder picker (move / copy) ---------- */
let pick = { path: "", its: [], op: "move" };
async function pickDest(its, op) {
  pick = { path: S.view === "files" ? S.path : "", its, op }; $("#pkTitle").textContent = (op === "move" ? "Move " : "Copy ") + (its.length === 1 ? `“${its[0].name}”` : its.length + " items") + " to";
  $("#pkOk").textContent = op === "move" ? "Move here" : "Copy here"; $("#dlgPick").showModal(); await pickLoad();
}
async function pickLoad() {
  const c = $("#pkCrumbs"), parts = pick.path ? pick.path.split("/") : []; c.replaceChildren(h("a", { href: "#", onclick: (e) => { e.preventDefault(); pick.path = ""; pickLoad(); } }, "My files"));
  parts.forEach((n, i) => c.append(h("span", {}, "›"), h("a", { href: "#", onclick: (e) => { e.preventDefault(); pick.path = parts.slice(0, i + 1).join("/"); pickLoad(); } }, n)));
  try {
    const d = await api("GET", "/api/files?" + qs({ root: S.root, path: pick.path })), dirs = d.items.filter((i) => i.type === "dir"), bad = new Set(pick.its.filter((i) => i.type === "dir").map((i) => i.path));
    $("#pkList").replaceChildren(...(dirs.length ? dirs.map((i) => { const p = joinPath(pick.path, i.name), b = h("button", { disabled: pick.op === "move" && bad.has(p), onclick: () => { pick.path = p; pickLoad(); } }, Object.assign(h("span", { class: "ico t-dir" }), { innerHTML: svg("folder") }), i.name); return b; }) : [h("div", { class: "empty", style: "padding:30px" }, "No subfolders")]));
  } catch (e) { toast(e.message, true); }
}
$("#pkNew").onclick = async () => { const n = await promptName("New folder", "", "Create"); if (!n) return; try { await api("POST", "/api/mkdir", { root: S.root, path: joinPath(pick.path, n) }); pick.path = joinPath(pick.path, n); pickLoad(); } catch (e) { toast(e.message, true); } };
$("#pkOk").onclick = async () => {
  try {
    const d = await api("POST", "/api/batch", { root: S.root, op: pick.op, paths: pick.its.map((i) => i.path), dest: pick.path });
    $("#dlgPick").close(); toast(d.errors.length ? d.errors[0].error : pick.op === "move" ? "Moved" : "Copied", !!d.errors.length); S.sel.clear(); refresh(); loadUsage();
  } catch (e) { toast(e.message, true); }
};

/* ---------- new menu, search ---------- */
$("#btnNew").onclick = (e) => { e.stopPropagation(); $("#newMenu").classList.toggle("hidden"); };
$$("#newMenu [data-act]").forEach((b) => (b.onclick = async () => {
  $("#newMenu").classList.add("hidden"); const a = b.dataset.act; if (S.view !== "files") await go("files");
  if (!canWrite()) return toast("This account is read-only", true);
  if (a === "uploadFiles") $("#fileInput").click(); else if (a === "uploadDir") $("#dirInput").click();
  else if (a === "newFolder") { const n = await promptName("New folder", "", "Create"); if (n) try { await api("POST", "/api/mkdir", { root: S.root, path: joinPath(S.path, n) }); refresh(); } catch (e) { toast(e.message, true); } }
  else if (a === "newText") { const n = await promptName("New text file", "untitled.txt", "Create", true); if (n) try { await api("PUT", "/api/text", { root: S.root, path: joinPath(S.path, n), content: "" }); await refresh(); const it = S.items.find((i) => i.name === n); if (it) editText(it); } catch (e) { toast(e.message, true); } }
}));
let searchT = null;
function doSearch() { S.query = $("#search").value.trim(); S.kind = $("#searchKind").value; if (!S.query && !S.kind) { if (S.view === "search") go("files"); return; } S.view = "search"; $$("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.nav === "files")); $("#viewAdmin").classList.add("hidden"); $("#viewFiles").classList.remove("hidden"); refresh(); }
$("#search").oninput = () => { clearTimeout(searchT); searchT = setTimeout(doSearch, 250); };
$("#searchKind").onchange = doSearch;

/* ---------- uploads (resumable, parallel) ---------- */
const UP = { queue: [], active: 0, total: 0, done: 0 };
$("#fileInput").onchange = (e) => { enqueue([...e.target.files].map((f) => ({ file: f, rel: f.name }))); e.target.value = ""; };
$("#dirInput").onchange = (e) => { enqueue([...e.target.files].map((f) => ({ file: f, rel: f.webkitRelativePath || f.name }))); e.target.value = ""; };
function enqueue(list) {
  if (!list.length) return; if (!canWrite()) return toast("This account is read-only", true);
  const base = S.view === "files" ? S.path : "", q = $("#queue"); q.classList.remove("hidden");
  if (!$("#qhead")) { q.replaceChildren(h("div", { class: "qh", id: "qhead" }, h("span", { id: "qtitle" }, "Uploading"), h("button", { class: "icon-btn", title: "Close", onclick: () => { if (!UP.active && !UP.queue.length) q.classList.add("hidden"); } })), h("div", { id: "qlist" })); $("#qhead button").innerHTML = svg("close"); }
  for (const { file, rel } of list) {
    const lab = h("span", {}, "waiting"), bar = h("progress", { max: 100, value: 0 }), row = h("div", { class: "qi" }, h("div", { class: "n" }, h("span", {}, rel), lab), bar);
    $("#qlist").append(row); UP.queue.push({ file, path: joinPath(base, rel), lab, bar, row, root: S.root }); UP.total++;
  }
  pump();
}
function pump() {
  while (UP.active < S.prefs.parallel && UP.queue.length) { const j = UP.queue.shift(); UP.active++; uploadOne(j).finally(() => { UP.active--; UP.done++; pump(); }); }
  $("#qtitle") && ($("#qtitle").textContent = UP.active || UP.queue.length ? `Uploading ${UP.done + 1} of ${UP.total}` : `${UP.total} upload${UP.total > 1 ? "s" : ""} complete`);
  if (!UP.active && !UP.queue.length) { UP.total = UP.done = 0; refresh(true); loadUsage(); setTimeout(() => { if (!UP.active && !UP.queue.length) $("#queue").classList.add("hidden"); }, 5000); }
}
async function uploadOne(j) {
  const CH = 8 * 1024 * 1024, f = j.file;
  try {
    const st = await api("POST", "/api/uploads", { root: j.root, path: j.path, size: f.size, mtime: f.lastModified / 1000 });
    let off = st.offset;
    do {
      const end = Math.min(off + CH, f.size);
      off = await new Promise((res, rej) => {
        const x = new XMLHttpRequest(); x.open("PATCH", `/api/uploads/${st.id}?${qs({ root: j.root })}`);
        x.setRequestHeader("Authorization", "Bearer " + S.token); x.setRequestHeader("Upload-Offset", String(off));
        x.upload.onprogress = (e) => { j.bar.value = ((off + e.loaded) / Math.max(1, f.size)) * 100; j.lab.textContent = Math.round(j.bar.value) + "%"; };
        x.onload = () => { if (x.status >= 200 && x.status < 300) res(JSON.parse(x.responseText).offset); else { let m = x.statusText; try { m = JSON.parse(x.responseText).detail || m; } catch (e) { /* ignore */ } rej(new Error(m)); } };
        x.onerror = () => rej(new Error("network")); x.send(f.slice(off, end));
      });
    } while (off < f.size);
    j.bar.value = 100; j.lab.textContent = "✓"; j.row.classList.add("done");
  } catch (e) { j.lab.textContent = "✕ " + e.message; j.row.classList.add("fail"); toast(`${f.name}: ${e.message}`, true); }
}
/* drag & drop from the desktop */
let dragDepth = 0;
const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
addEventListener("dragenter", (e) => { if (hasFiles(e)) { dragDepth++; $("#drop").classList.remove("hidden"); } });
addEventListener("dragleave", (e) => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; $("#drop").classList.add("hidden"); } });
addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
addEventListener("drop", async (e) => {
  dragDepth = 0; $("#drop").classList.add("hidden"); if (!hasFiles(e)) return; e.preventDefault();
  const out = [], walk = async (en, pre) => {
    if (en.isFile) await new Promise((r) => en.file((f) => { out.push({ file: f, rel: pre + f.name }); r(); }, r));
    else if (en.isDirectory) { const rd = en.createReader(); let b; do { b = await new Promise((r) => rd.readEntries(r, () => r([]))); for (const c of b) await walk(c, pre + en.name + "/"); } while (b.length); }
  };
  const its = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (its.length) for (const en of its) await walk(en, ""); else [...e.dataTransfer.files].forEach((f) => out.push({ file: f, rel: f.name }));
  enqueue(out);
});

/* ---------- preview ---------- */
let pv = { list: [], i: 0, url: null };
function previewList() { return sorted().filter((i) => PREVIEWABLE.has(kindOf(i))); }
async function preview(it) { pv.list = previewList(); pv.i = Math.max(0, pv.list.findIndex((x) => x.path === it.path)); if (!$("#dlgPreview").open) $("#dlgPreview").showModal(); await pvShow(); }
async function pvShow() {
  const it = pv.list[pv.i], body = $("#pvBody"); if (!it) return; $("#pvName").textContent = it.name; body.replaceChildren(h("div", { class: "nop" }, "Loading…"));
  $("#pvPrev").disabled = pv.i <= 0; $("#pvNext").disabled = pv.i >= pv.list.length - 1; if (pv.url) URL.revokeObjectURL(pv.url);
  try {
    const u = pv.url = await blobUrl(fileUrl(it.path)), k = kindOf(it), fail = (why) => body.replaceChildren(h("div", { class: "nop" }, why, h("div", { style: "margin-top:14px" }, h("button", { class: "btn primary", onclick: () => download(it) }, "Download"))));
    if (k === "image") {
      const im = h("img", { src: u, alt: it.name, draggable: false }); let z = 1, tx = 0, ty = 0, drag = null;
      const apply = () => { im.style.transform = `translate(${tx}px,${ty}px) scale(${z})`; im.style.cursor = z > 1 ? "grab" : "zoom-in"; };
      body.onwheel = (e) => { e.preventDefault(); z = Math.max(1, Math.min(8, z * (e.deltaY < 0 ? 1.15 : 1 / 1.15))); if (z === 1) tx = ty = 0; apply(); };
      im.onclick = () => { if (drag && drag.moved) return; z = z > 1 ? 1 : 2.5; if (z === 1) tx = ty = 0; apply(); };
      im.onpointerdown = (e) => { if (z > 1) { drag = { x: e.clientX - tx, y: e.clientY - ty, moved: false }; im.setPointerCapture(e.pointerId); } };
      im.onpointermove = (e) => { if (drag) { tx = e.clientX - drag.x; ty = e.clientY - drag.y; drag.moved = true; apply(); } };
      im.onpointerup = () => setTimeout(() => { drag = null; }, 0); im.onerror = () => fail("This image cannot be displayed by the browser.");
      body.replaceChildren(im); apply();
    } else if (k === "video") {
      const v = h("video", { src: u, controls: true, autoplay: true, playsinline: true });
      v.onerror = () => fail("This video format or codec is not supported by the browser. Download it to play it in another player (e.g. VLC).");
      body.replaceChildren(v);
    } else if (k === "audio") {
      const a = h("audio", { src: u, controls: true, autoplay: true }); a.onerror = () => fail("This audio format is not supported by the browser.");
      body.replaceChildren(h("div", { class: "audiocard" }, Object.assign(h("div", { class: "disc" }), { innerHTML: svg("audio") }), h("div", { class: "nm" }, it.name), a));
    } else body.replaceChildren(h("iframe", { src: u, title: it.name }));
  } catch (e) { body.replaceChildren(h("div", { class: "nop" }, "Cannot preview: " + e.message)); }
}
$("#pvClose").onclick = () => $("#dlgPreview").close(); $("#dlgPreview").onclose = () => { $("#pvBody").onwheel = null; $("#pvBody").replaceChildren(); if (pv.url) URL.revokeObjectURL(pv.url); pv.url = null; };
$("#pvPrev").onclick = () => { if (pv.i > 0) { pv.i--; pvShow(); } }; $("#pvNext").onclick = () => { if (pv.i < pv.list.length - 1) { pv.i++; pvShow(); } };
$("#pvDownload").onclick = () => download(pv.list[pv.i]); $("#pvShare").onclick = () => { const it = pv.list[pv.i]; $("#dlgPreview").close(); shareDialog(it); };
addEventListener("keydown", (e) => {
  if ($("#dlgPreview").open) { if (e.key === "ArrowLeft") $("#pvPrev").click(); if (e.key === "ArrowRight") $("#pvNext").click(); return; }
  if (document.querySelector("dialog[open]") || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || S.view === "admin" || !S.token) return;
  const its = selItems();
  if (e.key === "Delete" && its.length) { if (S.view === "trash") trashPurge(its); else if (canWrite()) trashSel(its); }
  else if (e.key === "F2" && its.length === 1 && canWrite() && S.view !== "trash") renameItem(its[0]);
  else if (e.key === "Enter" && its.length === 1) openItem(its[0]);
  else if (e.key === " " && its.length === 1 && S.view !== "trash") { e.preventDefault(); openItem(its[0]); }
  else if (e.key === "Backspace" && S.view === "files" && S.path) go("files", parentOf(S.path));
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") { e.preventDefault(); S.sel = new Set(S.items.map(selKey)); paintSel(); }
  else if (e.key === "Escape") { S.sel.clear(); paintSel(); }
});

/* ---------- sharing ---------- */
let shItem = null;
async function shareDialog(it) {
  shItem = it; $$(".people-only").forEach((e) => e.classList.toggle("hidden", !(it.type === "dir" && S.role !== "user" && S.root.indexOf("s:") !== 0)));
  if (it.type === "dir") { grList(); api("GET", "/api/people").then((d) => $("#grPeople").replaceChildren(...d.items.map((u) => h("option", { value: u.name }, u.display || u.name)))).catch(() => {}); } $("#shTitle").textContent = `Share “${it.name}”`; $("#shLink").classList.add("hidden"); $("#shPw").value = ""; $("#shMax").value = ""; $("#dlgShare").showModal(); await shareList();
}
async function shareList() {
  try {
    const d = await api("GET", "/api/shares?" + qs({ root: S.root, path: shItem.path || "" }));
    $("#shList").replaceChildren(...(d.items.length ? d.items.map((s) => h("div", { class: "listrow" }, h("div", { class: "grow" }, location.origin + "/s/" + s.token, h("div", { class: "muted small" }, (s.expires ? "expires " + fmtDate(s.expires) : "never expires") + (s.protected ? " · password" : "") + ` · ${s.downloads || 0} download${s.downloads === 1 ? "" : "s"}`)),
      h("button", { class: "btn text", onclick: () => copyText(location.origin + "/s/" + s.token) }, "Copy"), h("button", { class: "btn text danger", onclick: async () => { await api("DELETE", "/api/shares/" + s.token); shareList(); if (S.view === "shared") refresh(); } }, "Stop"))) : [h("div", { class: "muted" }, "No links yet.")]));
  } catch (e) { toast(e.message, true); }
}
async function grList() {
  try {
    const d = await api("GET", "/api/grants?" + qs({ root: S.root, path: shItem.path || "" }));
    $("#grList").replaceChildren(...d.given.map((g) => h("div", { class: "listrow" }, h("div", { class: "grow" }, g.to, h("span", { class: "muted" }, g.perm === "rw" ? " · can edit" : " · can view")),
      h("button", { class: "btn text danger", onclick: async () => { await api("DELETE", "/api/grants/" + g.id); grList(); } }, "Remove"))));
  } catch (e) { /* ignore */ }
}
$("#grForm").onsubmit = async (ev) => {
  ev.preventDefault(); const to = $("#grTo").value.trim(); if (!to) return;
  try { await api("POST", "/api/grants", { root: S.root, path: shItem.path, to, perm: $("#grPerm").value }); $("#grTo").value = ""; toast("Shared with " + to); grList(); } catch (e) { toast(e.message, true); }
};
async function copyText(t) { try { await navigator.clipboard.writeText(t); toast("Link copied"); } catch (e) { const i = h("input", { value: t }); document.body.append(i); i.select(); document.execCommand("copy"); i.remove(); toast("Link copied"); } }
$("#shForm").onsubmit = async (ev) => {
  ev.preventDefault();
  try {
    const d = await api("POST", "/api/shares", { root: S.root, path: shItem.path, days: +$("#shDays").value, password: $("#shPw").value, max_downloads: +$("#shMax").value || 0 });
    const url = location.origin + d.url, box = $("#shLink"); box.classList.remove("hidden");
    box.replaceChildren(h("input", { readonly: true, value: url, onfocus: (e) => e.target.select() }), h("button", { class: "btn tonal", type: "button", onclick: () => copyText(url) }, "Copy")); copyText(url); shareList();
  } catch (e) { toast(e.message, true); }
};

/* ---------- versions ---------- */
async function versionsDialog(it) {
  $("#vrTitle").textContent = `Version history — ${it.name}`; $("#vrList").replaceChildren(h("div", { class: "muted" }, "Loading…")); $("#dlgVersions").showModal();
  try {
    const d = await api("GET", "/api/versions?" + qs({ root: S.root, path: it.path }));
    $("#vrList").replaceChildren(h("div", { class: "listrow" }, h("div", { class: "grow" }, h("b", {}, "Current version"), h("div", { class: "muted small" }, fmtDate(it.mtime) + " · " + fmtSize(it.size)))),
      ...d.items.map((v) => h("div", { class: "listrow" }, h("div", { class: "grow" }, fmtDate(v.saved), h("div", { class: "muted small" }, fmtSize(v.size))),
        h("button", { class: "btn text", onclick: async () => saveVia(await authUrl("/api/versions/download", { root: S.root, path: it.path, id: v.id }), it.name) }, "Download"),
        canWrite() ? h("button", { class: "btn text", onclick: async () => { if (!(await confirmBox("Restore this version?", "The current file is kept as another version.", "Restore", false))) return; try { await api("POST", "/api/versions/restore", { root: S.root, path: it.path, id: v.id }); $("#dlgVersions").close(); toast("Version restored"); refresh(); } catch (e) { toast(e.message, true); } } }, "Restore") : null)),
      d.items.length ? null : h("div", { class: "muted", style: "padding:10px 0" }, `Older versions appear here when a file changes (the newest ${d.keep} are kept).`));
  } catch (e) { toast(e.message, true); }
}

/* ---------- text editor / viewer (line numbers, syntax colours, auto-indent) ---------- */
const KW = "abstract and as assert async await break case catch class const continue def default del delete do elif else enum except export extends false final finally fn for from function global if implements import in instanceof interface is lambda let match new none not null nonlocal of or package pass private protected pub public raise return self static struct super switch this throw true try type typeof undefined use var void while with yield impl mod mut trait where fun val when object override lateinit data sealed".split(" ");
const KWRE = new RegExp("\\b(" + KW.join("|") + ")\\b", "g"), HASHEXT = new Set(["py", "sh", "bash", "zsh", "yml", "yaml", "toml", "ini", "cfg", "conf", "rb", "ps1", "env", "gitignore", "r", "pl", "mk", "dockerfile", "txt", "properties", "slignore"]);
const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function highlight(text, ext) {
  if (text.length > 250000) return esc(text);
  const hash = HASHEXT.has(ext) || !ext, cm = hash ? "#[^\\n]*|" : "", sl = ["md", "txt", "csv", "log", "json"].includes(ext) ? "" : "\\/\\/[^\\n]*|";
  const strRe = "\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'|`(?:\\\\.|[^`\\\\])*`";
  const re = new RegExp("(" + sl + cm + "\\/\\*[\\s\\S]*?\\*\\/|<!--[\\s\\S]*?-->)|(" + strRe + ")|(\\b0x[0-9a-f]+\\b|\\b\\d[\\d_.]*(?:e[+-]?\\d+)?\\b)|(\\b[A-Za-z_]\\w*\\b)", "gi");
  let out = "", last = 0, m;
  while ((m = re.exec(text))) {
    out += esc(text.slice(last, m.index)); last = m.index + m[0].length; const t = esc(m[0]);
    if (m[1] !== undefined) out += `<i class="tk-c">${t}</i>`; else if (m[2] !== undefined) out += `<i class="tk-s">${t}</i>`; else if (m[3] !== undefined) out += `<i class="tk-n">${t}</i>`;
    else out += KW.includes(m[0].toLowerCase()) ? `<i class="tk-k">${t}</i>` : t;
  }
  return out + esc(text.slice(last));
}
let ed = null, edTimer = 0;
function edPaint() {
  const t = $("#edText"), v = t.value, ext = ed ? extOf(ed.it.name) : "";
  $("#edHi").innerHTML = highlight(v, ext) + "\n ";
  const n = v.split("\n").length; if (ed.lines !== n) { ed.lines = n; $("#edGutter").textContent = Array.from({ length: n }, (_, i) => i + 1).join("\n"); }
  edScroll();
}
function edScroll() { const t = $("#edText"); $("#edHi").scrollTop = t.scrollTop; $("#edHi").scrollLeft = t.scrollLeft; $("#edGutter").scrollTop = t.scrollTop; }
function edFont(px) { ed.font = Math.max(10, Math.min(26, px)); $("#dlgEdit").style.setProperty("--ed-font", ed.font + "px"); localStorage.setItem("sl_edfont", ed.font); }
async function editText(it) {
  try {
    const d = await api("GET", "/api/text?" + qs({ root: S.root, path: it.path })), ro = !canWrite();
    ed = { it, d, orig: d.content, ro, font: +localStorage.getItem("sl_edfont") || 13, lines: 0, find: "" };
    $("#edName").textContent = it.path; $("#edText").value = d.content; $("#edText").readOnly = ro; $("#edSave").classList.toggle("hidden", ro); $("#edRO").classList.toggle("hidden", !ro);
    edFont(ed.font); edDirty(false); edPaint(); edPos(); $("#edInfo").textContent = `${d.encoding} · ${d.eol.toUpperCase()} · ${extOf(it.name) || "plain text"}`;
    $("#dlgEdit").showModal(); $("#edText").scrollTop = 0; $("#edText").focus();
  } catch (e) { toast(e.message, true); }
}
const edDirty = (v) => { ed.dirty = v; $("#edDirty").classList.toggle("hidden", !v); };
function edPos() { const t = $("#edText"), s = t.value.slice(0, t.selectionStart).split("\n"); $("#edPos").textContent = `Ln ${s.length}, Col ${s[s.length - 1].length + 1}`; }
$("#edText").oninput = () => { edDirty($("#edText").value !== ed.orig); edPos(); cancelAnimationFrame(edTimer); edTimer = requestAnimationFrame(edPaint); };
$("#edText").onscroll = edScroll; $("#edText").onclick = $("#edText").onkeyup = edPos;
$("#edText").onkeydown = (e) => {
  const t = e.target, mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); if (!ed.ro) edSave(); return; }
  if (mod && e.key.toLowerCase() === "f") { e.preventDefault(); edFind(); return; }
  if (ed.ro) return;
  if (e.key === "Tab") {
    e.preventDefault(); const a = t.selectionStart, b = t.selectionEnd, v = t.value;
    if (a !== b && v.slice(a, b).includes("\n")) {
      const ls = v.lastIndexOf("\n", a - 1) + 1, block = v.slice(ls, b), out = e.shiftKey ? block.replace(/^( {1,4}|\t)/gm, "") : block.replace(/^/gm, "    ");
      t.setRangeText(out, ls, b, "select"); t.selectionStart = ls;
    } else if (e.shiftKey) { const ls = v.lastIndexOf("\n", a - 1) + 1, m = /^( {1,4}|\t)/.exec(v.slice(ls)); if (m) t.setRangeText("", ls, ls + m[0].length, "start"); }
    else t.setRangeText("    ", a, b, "end");
    t.dispatchEvent(new Event("input"));
  } else if (e.key === "Enter") {
    e.preventDefault(); const a = t.selectionStart, v = t.value, ls = v.lastIndexOf("\n", a - 1) + 1, ind = /^[ \t]*/.exec(v.slice(ls, a))[0], more = /[{(\[:]\s*$/.test(v.slice(ls, a)) ? "    " : "";
    t.setRangeText("\n" + ind + more, a, t.selectionEnd, "end"); t.dispatchEvent(new Event("input"));
  }
};
$("#edSmaller").onclick = () => edFont(ed.font - 1); $("#edBigger").onclick = () => edFont(ed.font + 1);
async function edFind() {
  const q = await ask({ title: "Find", ok: "Find next", input: { label: "Text to find", value: ed.find || "" } }); if (!q) { $("#edText").focus(); return; }
  const t = $("#edText"), v = t.value.toLowerCase(), needle = q.toLowerCase(); ed.find = q;
  let i = v.indexOf(needle, t.selectionEnd); if (i < 0) i = v.indexOf(needle); if (i < 0) { toast("No matches", true); t.focus(); return; }
  t.focus(); t.setSelectionRange(i, i + q.length); const line = v.slice(0, i).split("\n").length; t.scrollTop = Math.max(0, (line - 6) * ed.font * 1.5); edScroll(); edPos();
}
$("#edFind").onclick = edFind;
async function edSave() {
  try { const r = await api("PUT", "/api/text", { root: S.root, path: ed.it.path, content: $("#edText").value, encoding: ed.d.encoding, eol: ed.d.eol, mtime: ed.d.mtime }); ed.orig = $("#edText").value; if (r.mtime) ed.d.mtime = r.mtime; edDirty(false); toast("Saved"); refresh(true); }
  catch (e) { toast(e.message, true); }
}
$("#edSave").onclick = edSave;
$("#edClose").onclick = async () => { if (ed.dirty) { const r = await ask({ title: "Unsaved changes", message: "Save before closing?", ok: "Save", extra: "Discard" }); if (r === null) return; if (r) await edSave(); } $("#dlgEdit").close(); };
$("#dlgEdit").addEventListener("cancel", (e) => { e.preventDefault(); $("#edClose").click(); });

/* ---------- account & settings ---------- */
$("#btnAccount").onclick = () => {
  $("#acctInfo").replaceChildren(h("dt", {}, "Signed in as"), h("dd", {}, S.me.name), h("dt", {}, "Role"), h("dd", {}, S.role + (S.me.read_only ? " (read-only)" : "")), h("dt", {}, "Server"), h("dd", {}, location.host + (S.me.version ? " · v" + S.me.version : "")));
  $("#acctAdmin").classList.toggle("hidden", S.role !== "admin"); $("#acctMember").classList.toggle("hidden", S.role !== "member"); $("#acctNote").classList.toggle("hidden", S.role !== "user"); $("#dlgAccount").showModal();
};
if (window.SynclayerApp) { $("#acctApp").classList.remove("hidden"); $("#appServers").onclick = () => { closeDialogs(); SynclayerApp.servers(); }; $("#appBackup").onclick = () => { closeDialogs(); SynclayerApp.backup(); }; }
$("#pwForm").onsubmit = async (ev) => { ev.preventDefault(); try { await api("POST", "/api/admin/password", { new_password: $("#newPw").value }); $("#newPw").value = ""; toast("Password changed"); } catch (e) { toast(e.message, true); } };
$("#mpwForm").onsubmit = async (ev) => { ev.preventDefault(); try { await api("POST", "/api/account/password", { current: $("#mpCur").value, new_password: $("#mpNew").value }); $("#mpCur").value = $("#mpNew").value = ""; toast("Password changed"); } catch (e) { toast(e.message, true); } };
$("#btnSettings").onclick = () => { $("#pConfirm").checked = S.prefs.confirmDelete; $("#pIso").checked = S.prefs.iso; $("#pThumbs").checked = S.prefs.thumbs; $("#pPar").value = S.prefs.parallel; $("#dlgSettings").showModal(); };
$("#prefForm").onchange = () => { Object.assign(S.prefs, { confirmDelete: $("#pConfirm").checked, iso: $("#pIso").checked, thumbs: $("#pThumbs").checked, parallel: +$("#pPar").value }); savePrefs(); if (S.view !== "admin") render(); };

/* ---------- live updates ---------- */
function setLive(on) { const l = $("#live"); l.className = "live " + (on ? "on" : "off"); $("span", l).textContent = on ? "Live" : "Offline"; }
async function connectWS() {
  clearTimeout(S.wsTimer); if (!S.token) return;
  try {
    const { ticket } = await api("GET", "/api/ticket"), ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?ticket=${encodeURIComponent(ticket)}`);
    S.ws = ws; ws.onopen = () => { setLive(true); clearInterval(S.ping); S.ping = setInterval(() => { try { ws.send("ping"); } catch (e) { /* closed */ } }, 25000); };
    ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.event === "change" && d.root === S.root) { refreshSoon(); loadUsage(); } };
    ws.onclose = () => { clearInterval(S.ping); setLive(false); S.wsTimer = setTimeout(connectWS, 4000); };
  } catch (e) { S.wsTimer = setTimeout(connectWS, 6000); }
}

/* ---------- admin ---------- */
const FIELDS = [
  ["domain", "Public domain", "text"], ["storage_root", "Storage location (absolute path)", "text"], ["mounts", "Extra synced folders  name=/abs/path;name2=/abs/path", "text"],
  ["admin_user", "Admin username", "text"], ["max_upload_mb", "Max upload MB (0 = unlimited)", "number"], ["session_hours", "Session hours", "number"],
  ["quota_mb", "Storage quota MB (0 = unlimited)", "number"], ["min_free_mb", "Keep this many MB of disk free (0 = off)", "number"],
  ["user_quota_mb", "Default quota per person MB (0 = unlimited)", "number"], ["trash_days", "Keep deleted items for N days (0 = delete immediately)", "number"], ["versions_keep", "Old versions kept per file", "number"],
  ["blocked_extensions", "Blocked file types, e.g. .exe,.php", "text"], ["user_writes", "Device users may upload / change files", "checkbox"],
  ["read_only", "Read-only mode (blocks all writes)", "checkbox"], ["lockdown", "Lockdown (admin session only; device tokens rejected)", "checkbox"],
];
async function loadAdmin() {
  try {
    const d = await api("GET", "/api/admin/settings"), s = d.settings, form = $("#settingsForm");
    form.replaceChildren(...FIELDS.map(([k, label, type]) => {
      let val = s[k]; if (k === "mounts") val = Object.entries(val || {}).map(([a, b]) => a + "=" + b).join(";");
      return type === "checkbox" ? h("label", { class: "check" }, h("input", { type, id: "f_" + k, checked: !!val }), label) : h("label", {}, label, h("input", { type, id: "f_" + k, value: val ?? "" }));
    }), h("button", { class: "btn primary", type: "submit" }, "Apply"), h("p", { class: "muted small" }, `Listening on ${s.host}:${s.port} (restart to change)`));
    const du = d.disk || {}; $("#disk").textContent = du.total ? `Disk: ${fmtSize(du.used)} used of ${fmtSize(du.total)} (${fmtSize(du.free)} free)` : "";
    loadTokens(); loadDevices(); loadStorage(); loadUsers();
  } catch (e) { toast(e.message, true); }
}
const ago = (s) => (s == null ? "never" : s < 10 ? "just now" : s < 90 ? s + "s ago" : s < 5400 ? Math.round(s / 60) + " min ago" : s < 172800 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " d ago");
const devKind = (a) => (!a ? "unknown" : /Android/i.test(a) ? "Android" : /Windows/i.test(a) ? "Windows" : /Linux|X11/i.test(a) ? "Linux" : /Mac/i.test(a) ? "macOS" : /python|httpx|synclayer/i.test(a) ? "Desktop / CLI" : a.slice(0, 24));
let devTimer = null;
async function loadUsers() {
  try {
    const d = await api("GET", "/api/admin/users");
    $("#userList").replaceChildren(...(d.items.length ? d.items.map((u) => h("div", { class: "listrow" },
      h("div", { class: "grow" }, h("b", {}, u.name), u.disabled ? h("span", { class: "pill off" }, "disabled") : null,
        h("div", { class: "muted small" }, `${sz(u.used)} used` + (u.quota_mb || d.default_quota_mb ? ` of ${sz((u.quota_mb || d.default_quota_mb) * 1048576)}` : ""))),
      h("button", { class: "btn text", onclick: async () => { const q = await promptName("Quota for " + u.name + " (MB, 0 = default)", String(u.quota_mb || 0), "Save", true); if (q == null) return; try { await api("PATCH", "/api/admin/users/" + u.name, { quota_mb: Math.max(0, parseInt(q, 10) || 0) }); loadUsers(); } catch (e) { toast(e.message, true); } } }, "Quota"),
      h("button", { class: "btn text", onclick: async () => { const pw = await ask({ title: "New password for " + u.name, ok: "Set password", input: { label: "Password (8+ characters)", type: "password", validate: (v) => (v.length < 8 ? "At least 8 characters." : "") } }); if (!pw) return; try { await api("PATCH", "/api/admin/users/" + u.name, { password: pw }); toast("Password changed"); } catch (e) { toast(e.message, true); } } }, "Password"),
      h("button", { class: "btn text", onclick: async () => { try { await api("PATCH", "/api/admin/users/" + u.name, { disabled: !u.disabled }); loadUsers(); } catch (e) { toast(e.message, true); } } }, u.disabled ? "Enable" : "Disable"),
      h("button", { class: "btn text danger", onclick: async () => { const r = await ask({ title: "Remove " + u.name + "?", message: "Their sign-ins and shares stop working. Their files are kept in a hidden folder on the server unless you delete them too.", ok: "Remove, keep files", danger: true, extra: "Remove and delete files" }); if (r === null) return; try { await api("DELETE", "/api/admin/users/" + u.name + "?purge=" + (r === false)); loadUsers(); } catch (e) { toast(e.message, true); } } }, "Remove"))) : [h("div", { class: "muted" }, "No one yet. Add a person above.")]));
  } catch (e) { /* ignore */ }
}
$("#userForm").onsubmit = async (ev) => {
  ev.preventDefault();
  try { await api("POST", "/api/admin/users", { name: $("#uName").value.trim(), password: $("#uPass").value, quota_mb: +$("#uQuota").value || 0 }); $("#uName").value = $("#uPass").value = $("#uQuota").value = ""; toast("Person added"); loadUsers(); } catch (e) { toast(e.message, true); }
};
async function loadDevices() {
  try {
    const d = await api("GET", "/api/admin/devices"), c = $("#devCount"); c.textContent = d.online + " online / " + d.total; c.className = "pill " + (d.online ? "on" : "off");
    const l = d.last; $("#lastDev").textContent = l ? `Last connected: ${l.name} (${devKind(l.agent)}${l.last_ip ? ", " + l.last_ip : ""}) ${ago(l.ago)}` : "No device has connected yet.";
    $("#devRows").replaceChildren(...d.devices.map((t) => h("tr", {}, h("td", {}, h("span", { class: "pill " + (t.online ? "on" : "off") }, t.live ? "LIVE" : t.online ? "ONLINE" : "OFFLINE")), h("td", {}, t.name), h("td", { class: "muted" }, devKind(t.agent)), h("td", { class: "r muted" }, ago(t.ago)))));
  } catch (e) { /* ignore */ }
  clearTimeout(devTimer); if (S.view === "admin") devTimer = setTimeout(loadDevices, 15000);
}
async function loadStorage() {
  try {
    const d = await api("GET", "/api/admin/usage"), total = d.quota || (d.disk && d.disk.total) || 1;
    const kids = [h("div", {}, d.quota ? `${sz(d.used)} of ${sz(d.quota)} quota` : `${sz(d.used)} used (no quota)`), h("progress", { max: total, value: Math.min(d.used, total) })];
    if (d.disk && d.disk.total) kids.push(h("div", { class: "muted" }, `Disk free: ${sz(d.disk.free)}` + (d.reserve ? ` (reserve ${sz(d.reserve)})` : "")));
    if (d.top && d.top.length) kids.push(h("table", { class: "mini" }, h("tbody", {}, d.top.map((t) => h("tr", {}, h("td", {}, (t.type === "dir" ? "📁 " : "") + t.name), h("td", { class: "r muted" }, sz(t.size)))))));
    $("#storage").replaceChildren(...kids);
  } catch (e) { $("#storage").textContent = ""; }
}
$("#settingsForm").onsubmit = async (ev) => {
  ev.preventDefault(); const changes = {};
  for (const [k, , type] of FIELDS) { const el = $("#f_" + k); changes[k] = type === "checkbox" ? el.checked : type === "number" ? Number(el.value) : el.value; }
  try { await api("PATCH", "/api/admin/settings", { changes }); toast("Settings applied"); loadAdmin(); } catch (e) { toast(e.message, true); }
};
async function loadTokens() {
  const d = await api("GET", "/api/admin/tokens");
  $("#tokRows").replaceChildren(...d.tokens.map((t) => h("tr", {}, h("td", {}, t.name + (t.read_only ? " (read-only)" : "")), h("td", { class: "muted" }, new Date(t.created * 1000).toLocaleDateString()),
    h("td", { class: "r" }, h("button", { class: "btn text danger", onclick: async () => { if (!(await confirmBox("Revoke token?", `“${t.name}” will no longer be able to sign in.`, "Revoke"))) return; await api("DELETE", "/api/admin/tokens/" + t.id); loadTokens(); } }, "Revoke")))));
}
$("#tokForm").onsubmit = async (ev) => {
  ev.preventDefault();
  try { const d = await api("POST", "/api/admin/tokens", { name: $("#tokName").value || "device", read_only: $("#tokRO").checked }); const box = $("#newTok"); box.classList.remove("hidden"); box.textContent = "Copy now (shown once): " + d.token; $("#tokName").value = ""; loadTokens(); } catch (e) { toast(e.message, true); }
};
$("#rotate").onclick = async () => {
  if (!(await confirmBox("Rotate secret?", "Every admin session, including this one on other devices, must sign in again.", "Rotate"))) return;
  try { const d = await api("POST", "/api/admin/rotate-secret"); S.token = d.token; saveToken(d.token, !!localStorage.getItem("sl_token")); toast("Secret rotated"); } catch (e) { toast(e.message, true); }
};

/* ---------- boot ---------- */
(async function init() {
  S.token = localStorage.getItem("sl_token") || sessionStorage.getItem("sl_token");
  if (S.token) { try { await start(); return; } catch (e) { S.token = null; } }
  $("#login").classList.remove("hidden");
})();
