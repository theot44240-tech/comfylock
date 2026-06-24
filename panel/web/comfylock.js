// ComfyLock ComfyUI front-end extension (v0.3.0).
// Adds Save / Verify / Inspect / Update buttons, a status badge, and an opt-in
// "auto-pack on save" setting, all backed by the /comfylock/* routes registered
// in panel/__init__.py. Vanilla JS + fetch — no build step.

import { app } from "../../scripts/app.js";

const BADGE = { OK: "#3fb950", WARN: "#d29922", ERR: "#f85149", IDLE: "#6e7681" };
let lastLock = null; // remembers the most recently packed lock (graph snapshot)

function mkButton(label, title, onClick) {
  const b = document.createElement("button");
  b.textContent = label;
  b.title = title;
  b.style.cssText = "margin:2px;padding:4px 8px;cursor:pointer;";
  b.onclick = onClick;
  return b;
}

async function postJSON(route, body) {
  const res = await fetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || `${route} failed`);
  }
  return res;
}

function currentGraphBody() {
  return { workflow: app.graph.serialize(), name: "workflow.flow.json" };
}

function showModal(title, text) {
  const overlay = document.createElement("div");
  overlay.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:2000;" +
    "display:flex;align-items:center;justify-content:center;";
  const box = document.createElement("div");
  box.style.cssText =
    "background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:8px;" +
    "max-width:80vw;max-height:80vh;overflow:auto;padding:16px;font:13px/1.4 monospace;";
  const h = document.createElement("div");
  h.textContent = title;
  h.style.cssText = "font-weight:bold;margin-bottom:8px;";
  const pre = document.createElement("pre");
  pre.textContent = text;
  pre.style.cssText = "white-space:pre-wrap;margin:0;";
  box.appendChild(h);
  box.appendChild(pre);
  overlay.appendChild(box);
  overlay.onclick = () => overlay.remove();
  document.body.appendChild(overlay);
}

function setBadge(dot, color, title) {
  dot.style.background = color;
  dot.title = title;
}

async function refreshBadge(dot) {
  if (!lastLock) {
    setBadge(dot, BADGE.WARN, "ComfyLock: no lockfile saved for this workflow");
    return;
  }
  try {
    const res = await postJSON("/comfylock/verify", { lock: lastLock, hash: false });
    const data = await res.json();
    if (data.passed) setBadge(dot, BADGE.OK, "ComfyLock: verify passes");
    else setBadge(dot, BADGE.ERR, `ComfyLock: ${data.errors} mismatch(es)`);
  } catch (e) {
    setBadge(dot, BADGE.IDLE, "ComfyLock: " + e.message);
  }
}

async function doSave(dot) {
  const res = await postJSON("/comfylock/pack", currentGraphBody());
  const text = await res.text();
  lastLock = JSON.parse(text);
  // Trigger a download of the .lock file.
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "workflow.lock";
  a.click();
  URL.revokeObjectURL(url);
  if (dot) refreshBadge(dot);
}

app.registerExtension({
  name: "comfylock.panel",
  async setup() {
    // Opt-in auto-pack-on-save setting.
    let autoPack = false;
    try {
      app.ui.settings.addSetting({
        id: "comfylock.autoPack",
        name: "ComfyLock: auto-pack on workflow save",
        type: "boolean",
        defaultValue: false,
        onChange: (v) => { autoPack = !!v; },
      });
    } catch (e) { /* older ComfyUI without settings API */ }

    const badge = document.createElement("span");
    badge.style.cssText =
      "display:inline-block;width:10px;height:10px;border-radius:50%;margin:2px 6px;vertical-align:middle;";
    setBadge(badge, BADGE.IDLE, "ComfyLock");

    const save = mkButton("🔒 Save Lockfile", "Pin models, node commits and parameters", async () => {
      save.disabled = true;
      try { await doSave(badge); } catch (e) { alert("ComfyLock: " + e.message); }
      finally { save.disabled = false; }
    });

    const verify = mkButton("✅ Verify", "Verify the current install against the saved lock", async () => {
      if (!lastLock) { alert("ComfyLock: save a lockfile first."); return; }
      try {
        const res = await postJSON("/comfylock/verify", { lock: lastLock, hash: true });
        const data = await res.json();
        showModal("ComfyLock — verify", data.issues.map((i) => `${i.severity}  ${i.message}`).join("\n"));
        refreshBadge(badge);
      } catch (e) { alert("ComfyLock: " + e.message); }
    });

    const inspect = mkButton("📋 Inspect", "Show a summary of the current graph's lock", async () => {
      try {
        const res = await postJSON("/comfylock/inspect", currentGraphBody());
        const data = await res.json();
        showModal("ComfyLock — inspect", data.text);
      } catch (e) { alert("ComfyLock: " + e.message); }
    });

    const update = mkButton("🔄 Update", "Refresh pinned node commits", async () => {
      if (!lastLock) { alert("ComfyLock: save a lockfile first."); return; }
      try {
        const res = await postJSON("/comfylock/update", { lock: lastLock });
        const data = await res.json();
        showModal("ComfyLock — update", data.changes.length ? data.changes.join("\n") : "Already up to date.");
      } catch (e) { alert("ComfyLock: " + e.message); }
    });

    // Auto-pack hook: wrap graphToPrompt-less save by listening for Ctrl+S.
    document.addEventListener("keydown", (ev) => {
      if (autoPack && (ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
        doSave(badge).catch(() => {});
      }
    });

    const menu = document.querySelector(".comfy-menu");
    const host = document.createElement("span");
    host.appendChild(badge);
    [save, verify, inspect, update].forEach((b) => host.appendChild(b));
    if (menu) {
      menu.appendChild(host);
    } else {
      host.style.cssText = "position:fixed;top:8px;right:8px;z-index:1000;background:#0d1117;padding:4px;border-radius:6px;";
      document.body.appendChild(host);
    }
    refreshBadge(badge);
  },
});
