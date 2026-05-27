// Alpine store for the GitNexus Canvas surface. On mount it asks the plugin API to start the
// `gitnexus serve` web UI and loads the returned proxied URL into the panel iframe. The gitnexus
// SPA inside that iframe renders the code graph and handles its own layout/interaction, so this
// store only manages the iframe src + status (route 1: web-served tool, no bridge).
import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const model = {
  frameSrc: "",
  status: "Starting GitNexus…",
  loading: false,

  async onMount() {
    if (this.frameSrc || this.loading) return;  // idempotent (x-create + register open() may both fire)
    await this.start();
  },

  async start() {
    this.loading = true;
    this.frameSrc = "";
    this.status = "Starting GitNexus…";
    try {
      const res = await callJsonApi("/plugins/gitnexus/gitnexus_surface", { action: "open" });
      if (res && res.ok && res.url) {
        this.frameSrc = res.url;
        this.status = "";
      } else {
        this.status = (res && res.error) || "Could not start GitNexus. Check the plugin is enabled.";
      }
    } catch (e) {
      this.status = "Could not start GitNexus: " + (e?.message || e);
    } finally {
      this.loading = false;
    }
  },

  cleanup() {
    this.frameSrc = "";
    this.loading = false;
  },
};

export const store = createStore("gitnexus", model);
