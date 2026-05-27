"""API for the GitNexus Canvas surface.

The surface (webui/gitnexus-surface.html + gitnexus-store.js) calls this (POST
/plugins/gitnexus/gitnexus_surface) when it mounts:
  action=open  -> start `gitnexus serve` + a headless Chromium rendering it + the CDP screencast
                  bridge, register the bridge with A0's virtual-desktop gateway, and return the
                  proxied {url} the surface iframes (route 2 — the gitnexus web UI is local-only).
  action=close -> unregister the gateway session (the processes keep running for instant re-open).
Runs in the web-server process, so register_session() lands in the gateway's in-process registry.
"""

from __future__ import annotations

from helpers.api import ApiHandler, Request
from usr.plugins.gitnexus.helpers import setup


class GitnexusSurface(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        action = str(input.get("action") or "open").lower().strip()
        cfg = setup._config()
        if action == "close":
            setup.stop_surface_session(cfg)
            return {"ok": True, "closed": True}
        try:
            url = setup.start_surface_session(cfg)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not url:
            return {
                "ok": False,
                "error": "Could not start GitNexus (is the gitnexus CLI installed and the plugin enabled?).",
            }
        return {"ok": True, "url": url}
