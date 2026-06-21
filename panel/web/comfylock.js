// ComfyLock ComfyUI front-end extension.
// Adds a "🔒 Save Lockfile" button that pins the current graph into a .lock file
// by calling the POST /comfylock/pack route registered in panel/__init__.py.

import { app } from "../../scripts/app.js";

app.registerExtension({
  name: "comfylock.panel",
  async setup() {
    const button = document.createElement("button");
    button.textContent = "🔒 Save Lockfile";
    button.title = "Pin models, node commits and parameters into a ComfyLock .lock file";
    button.style.cssText = "margin:2px;padding:4px 8px;cursor:pointer;";

    button.onclick = async () => {
      button.disabled = true;
      const old = button.textContent;
      button.textContent = "Locking…";
      try {
        const graph = app.graph.serialize();
        const res = await fetch("/comfylock/pack", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ workflow: graph, name: "workflow.flow.json" }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ error: res.statusText }));
          throw new Error(err.error || "pack failed");
        }
        const text = await res.text();
        const blob = new Blob([text], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "workflow.lock";
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        alert("ComfyLock: " + e.message);
      } finally {
        button.textContent = old;
        button.disabled = false;
      }
    };

    // Attach to the ComfyUI menu if present, otherwise float top-right.
    const menu = document.querySelector(".comfy-menu");
    if (menu) {
      menu.appendChild(button);
    } else {
      button.style.cssText += "position:fixed;top:8px;right:8px;z-index:1000;";
      document.body.appendChild(button);
    }
  },
});
