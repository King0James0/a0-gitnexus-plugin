// Registers the "GitNexus" surface in the right-side Canvas rail (alongside Browser/Desktop/
// Editor/Obsidian). On open it mounts the store, which starts `gitnexus serve` and loads its graph
// web UI into the docked panel. Mirrors the built-in _editor surface registration (importing the
// store + an open() handler is what actually bootstraps the panel — the panel's x-create alone is
// not sufficient). The modal file is NOT named main.html (that would add a stray Plugins-list
// "Open" button via has_main_screen).
import { store as gitnexusStore } from "/plugins/gitnexus/webui/gitnexus-store.js";

function waitForElement(selector, timeoutMs = 10000) {
  const found = document.querySelector(selector);
  if (found) return Promise.resolve(found);
  return new Promise((resolve) => {
    const timeout = globalThis.setTimeout(() => {
      observer.disconnect();
      resolve(document.querySelector(selector));
    }, timeoutMs);
    const observer = new MutationObserver(() => {
      const element = document.querySelector(selector);
      if (!element) return;
      globalThis.clearTimeout(timeout);
      observer.disconnect();
      resolve(element);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
}

export default async function registerGitnexusSurface(surfaces) {
  surfaces.registerSurface({
    id: "gitnexus",
    title: "GitNexus",
    icon: "account_tree", // material symbol — a code/dependency-graph glyph
    order: 41,
    modalPath: "/plugins/gitnexus/webui/gitnexus-surface.html",
    async open() {
      const panel = await waitForElement('[data-surface-id="gitnexus"] .gitnexus-panel');
      if (panel) await gitnexusStore.onMount?.(panel);
    },
    async close() {
      gitnexusStore.cleanup?.();
    },
  });
}
