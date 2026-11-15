"use strict";
const $ = (s) => document.querySelector(s);
const token = location.pathname.split("/").filter(Boolean).pop();
let pw = "", sub = "";
const qs = (o) => new URLSearchParams(Object.fromEntries(Object.entries(o).filter(([, v]) => v))).toString();
const fmt = (n) => { const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return n.toFixed(i ? 1 : 0) + " " + u[i]; };
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const url = (p, o) => `/api/public/${token}${p}?${qs(o)}`;

async function load() {
  $("#err").textContent = "";
  const r = await fetch(url("", { sub, pw }));
  if (r.status === 401) {
    $("#shName").textContent = "Password needed"; $("#pwForm").classList.remove("hidden");
    if (pw) $("#err").textContent = "Wrong password.";
    return;
  }
  if (!r.ok) {
    $("#shName").textContent = "Link unavailable";
    $("#shMeta").textContent = (await r.json().catch(() => ({}))).detail || "This link has expired or does not exist.";
    return;
  }
  $("#pwForm").classList.add("hidden");
  const d = await r.json();
  $("#shName").textContent = d.name || "Shared folder";
  const dl = $("#dl"); dl.classList.remove("hidden"); dl.href = url("/download", { sub, pw });
  dl.textContent = d.type === "dir" ? "Download as .zip" : "Download";
  $("#shMeta").textContent = d.type === "file" ? fmt(d.size) : d.items.length + " items";
  const pv = $("#pv"); pv.replaceChildren();
  if (d.type === "file" && d.previewable) {
    const src = url("/download", { sub, pw, inline: "true" }), n = d.name.toLowerCase();
    let node;
    if (/\.(png|jpe?g|gif|webp|avif|bmp|ico)$/.test(n)) { node = el("img"); node.src = src; }
    else if (/\.(mp4|m4v|webm|mov)$/.test(n)) { node = el("video"); node.src = src; node.controls = true; }
    else if (/\.(mp3|m4a|wav|ogg|flac|opus)$/.test(n)) { node = el("audio"); node.src = src; node.controls = true; }
    else { node = el("iframe"); node.src = src; node.className = "pdf"; }
    pv.append(node);
  }
  const crumbs = $("#crumbs"); crumbs.replaceChildren();
  if (d.type === "dir") {
    const parts = sub ? sub.split("/") : [];
    const root = el("a", "", "Shared folder"); root.onclick = () => { sub = ""; load(); }; crumbs.append(root);
    parts.forEach((p, i) => { crumbs.append(el("span", "", "/")); const a = el("a", "", p); a.onclick = () => { sub = parts.slice(0, i + 1).join("/"); load(); }; crumbs.append(a); });
  }
  const list = $("#list"); list.replaceChildren();
  for (const it of d.items || []) {
    const row = el("div", "shrow");
    const full = [sub, it.name].filter(Boolean).join("/");
    const a = el("a", "", (it.type === "dir" ? "📁 " : "📄 ") + it.name);
    if (it.type === "dir") a.onclick = () => { sub = full; load(); };
    else a.href = url("/download", { sub: full, pw });
    row.append(a, el("span", "muted", it.type === "dir" ? "" : fmt(it.size)));
    list.append(row);
  }
}
$("#pwForm").onsubmit = (e) => { e.preventDefault(); pw = $("#pw").value; load(); };
load();
