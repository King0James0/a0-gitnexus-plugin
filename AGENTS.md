# AGENTS.md — operating contract for `a0-gitnexus-plugin`

You are working on an Agent Zero plugin that installs a third-party CLI (`gitnexus`), registers an
**MCP server** into the user's A0 settings, runs a **headless Chromium + CDP screencast bridge** for
a Canvas graph view, and registers a **scheduled re-index task**. A mistake here mutates the user's
shared `mcp_servers` setting, leaves orphaned processes/binaries/tasks behind on uninstall, exposes a
loopback debugging surface to the network, or blocks A0 startup. Follow these rules exactly. They are
not suggestions.

## What this plugin is
A self-contained A0 plugin (`gitnexus`, id in `plugin.yaml`). It gives the agent code-graph powers by
(1) installing the `gitnexus` npm CLI and registering its `gitnexus mcp` stdio server so the MCP tools
appear in the toolset; (2) adding a **GitNexus Canvas surface** that screencasts the CLI's local-only
`gitnexus serve` web UI (rendered in an in-container headless Chromium, streamed over A0's `/desktop`
gateway); and (3) registering an **opt-in** (off by default) **commit-aware re-index** ScheduledTask
that refreshes already-indexed repos whose HEAD moved. No API key. Publishable, model-agnostic,
uninstall-clean.

## HARD INVARIANTS — never violate
1. **Setup is best-effort — it must NEVER block A0 startup.** Every entry point in `helpers/setup.py`
   (`ensure`, `register_mcp`, `ensure_binary`, the surface launchers, `register_reindex_task`) LOGS
   and RETURNS on any failure — never raises. The `_50_gitnexus_setup` boot extension calls
   `setup.ensure()` synchronously at framework startup; a raise there breaks every boot.
2. **MCP registration is idempotent on boot, forced only on install.** `register_mcp(force=False)`
   (every boot) SKIPS if the entry is already present — never re-write `mcp_servers`, because A0
   reloads/reconnects MCP whenever that setting changes (churning it on each boot drops the agent's
   tools mid-session). `force=True` is install-only (drop-then-re-add to nudge a reconnect). Always go
   through `helpers.settings.set_settings_delta` — NEVER edit `settings.json` on disk.
3. **Uninstall removes ONLY what THIS plugin added.** `cleanup()` + `_uninstall_binary_if_ours()` are
   gated on markers (`.installed-gitnexus`, `.installed-gitnexus-chromium`): if the user had `gitnexus`
   or chromium installed independently, leave them. `unregister_reindex_task()` removes the task by the
   stored uuid (`.reindex-task-uuid`) falling back to name. Never `rm -rf` a user's indexed repos or
   their `~/.gitnexus` data. Removing the plugin folder by hand bypasses this — always uninstall via UI.
4. **The Canvas surface stays on `127.0.0.1` — never bind a port to a routable interface.**
   `gitnexus serve` (`serve_port`), the Chromium CDP/remote-debugging port (`cdp_port`), and the
   screencast bridge (`bridge_port`) ALL bind loopback only (`--host 127.0.0.1` / `--listen-host
   127.0.0.1`). The CDP port is an unauthenticated full-control debug channel — exposing it is RCE.
   Only screencast pixels cross A0's gateway; the SSE-over-localhost SPA is the whole reason for the
   screencast route. The bridge's nav-guard (`_NAV_GUARD_JS` + `Bridge._on_navigated` snap-back) keeps
   the headless browser pinned to the app origin — keep both guards intact. The bridge also injects an
   **app-guard** (`_APP_GUARD_JS`: hides upstream chrome that's dead in the embedded canvas — Nexus AI,
   its AI Settings gear, the Star / Sponsor CTAs, and the AI output-language selector — and on a
   blank/crash overlays a message + returns to the repo picker) and runs
   a **WebGL self-heal** (`webgl_health`): the app-guard installs a `webglcontextlost` listener that
   sets `window.__a0glLost`; the coroutine only READS that flag and relaunches via `_kill_renderer` on
   a real loss. It MUST NEVER probe by creating its own canvas/context — Chromium caps active WebGL
   contexts (~16) and a per-tick probe accumulates contexts that evict the graph's own (white-on-idle,
   the v1.2.14 fix). Keep these intact.
5. **The runtime dir lives OUT of the watched plugin tree.** `_runtime_dir()` returns
   `usr/gitnexus-runtime` (the Chromium profile, logs, `relaunch.json`). A0 watches plugin roots
   recursively; the Chromium profile churns the filesystem and would trip A0's startup-watchdog
   registration into a deadlock if kept under the plugin dir. Never relocate runtime state back inside
   the plugin folder; `cleanup()` removes this dir on uninstall.
6. **The scheduled task is OPT-IN (off by default), config-driven, reconciled to its toggle.**
   `reconcile_reindex_task()` keys on `reindex.enabled`: enabled → ensure the task exists and set its
   cadence from config — `_reindex_schedule()` maps `reindex.cron` (a valid custom cron wins) or the
   `reindex.interval` preset (6h/12h/1d/7d/30d) to a TaskSchedule, applied on EVERY reconcile (config
   is the SOURCE OF TRUTH, like github-watch — Scheduler edits get overwritten); the pre-1.2.8
   "GitNexus weekly re-index" is renamed in place (uuid kept). disabled → remove it. Runs on
   `install`, on boot (`startup_migration/_55`), and on `save_plugin_config` (live toggle, no restart).
   The reused task context is reset each run by `monologue_start/_56` (gated on `reindex.reset_context`
   default on + the task ctx id; mirrors github's `_80`) so it can't grow unbounded. The WORKER
   (`reindex.py`) is **refresh-changed-only**: NEVER discovers/indexes new repos, only re-runs `analyze`
   on already-indexed git work-trees whose HEAD moved (`--skip-agents-md` keeps this DOX pure).
7. **`reindex.py` is pure stdlib — no Agent Zero imports.** It runs as a bare script
   (`python3 .../helpers/reindex.py`) launched by the agent's code-exec tool from the ScheduledTask;
   there is NO background thread, so it can never double-fire. Keep it framework-free and best-effort
   (per-repo try/except, bounded subprocess timeouts) so one bad repo can't fail the run.
8. **The re-index runs exactly once per cycle.** `tool_execute_before/_30_gitnexus_reindex_once` blocks
   a weak utility model from re-running `reindex.py` within one scheduled run (RepairableException;
   keyed on the run's `last_user_message.id` so it self-resets each cycle; scoped to the task's OWN
   context id so a manual run in a normal chat is unaffected). `helpers/run_once.py` holds the
   sys-attached state. Always on (no config knob).

## Build discipline
- **Framework boundary.** Only `helpers/setup.py`, `hooks.py`, the `api/` handler, and the
  `extensions/` files import Agent Zero (`from helpers...`, `usr.plugins.gitnexus...`).
  `helpers/reindex.py` and `helpers/screencast.py` are standalone stdlib/subprocess scripts — keep them
  importable and runnable with no A0 present.
- **Per change:** `py_compile` every `.py` via `/opt/venv-a0/bin/python -m py_compile`; keep
  `default_config.yaml` ↔ the README config table ↔ the keys read in `setup.py` in lockstep; bump
  `plugin.yaml` `version` on a release and cut a tagged GitHub Release with notes.
- **Keep THIS file current.** Update this AGENTS.md in the SAME change whenever you alter a HARD INVARIANT, a cited path/seam/A0 mechanic, or what this plugin is — a stale contract MISLEADS (worse than none). Routine fixes/features that don't change the contract don't touch it.
- **Validate in a THROWAWAY, never a live A0.** Snapshot/commit the instance into an isolated
  container; never mutate the user's live `mcp_servers`, indexed repos, or scheduled tasks. Verify the
  Canvas surface renders in a real browser. (The maintainer installs the built artifact via the UX.)
- **Opsec (public repo):** no secrets, IPs, internal hostnames, personal email, or local paths in
  shipped files. `CLAUDE.md` + `.claude/` are dev-only and gitignored (excluded from the published
  repo). Commits: single human author (King0James0), GitHub no-reply email, NO AI / `Co-Authored-By`
  trailers.

## Knowledge map (one source of truth each — never duplicate)
- **User-facing behaviour** (what it does, setup, the schedule, config table, uninstall): `README.md`.
- **Config defaults** (versions, ports, schedule, all overridable per-scope): `default_config.yaml`.
- **Agent process knowledge** (how to index + query the graph; how to show the Canvas surface):
  `skills/gitnexus-code-graph/` and `skills/gitnexus-canvas-view/` (shipped, agent-facing).
- **Mechanical truth** (callers/callees, blast radius): GitNexus itself — its index block lives in the
  gitignored `CLAUDE.md`, not here. Re-index with `gitnexus analyze --skip-agents-md` to keep this DOX
  pure (the re-index worker already passes that flag).

## Verified A0 mechanics (don't re-derive — confirm against the LIVE instance; versions move constantly)
- Hooks/seams: `install()`/`uninstall()`/`save_plugin_config` in `hooks.py` (async install/uninstall —
  A0 runs coroutine hooks via `asyncio.run`; `save_plugin_config` is sync = the live re-index toggle) ·
  `startup_migration/_50` (`ensure()` every boot — re-installs the CLI/MCP into the ephemeral venv) +
  `_55` (reconcile the re-index task) · `monologue_start/_56` (reset the re-index task context) ·
  `tool_execute_before/_30` (re-index exactly-once guard) · the `api/` ApiHandler
  (`POST /plugins/gitnexus/gitnexus_surface`, action open/close — runs in the web-server process so
  `virtual_desktop.register_session` lands in the in-process gateway registry) · the Canvas surface
  (`register-gitnexus.js` + `gitnexus-surface.html` + `gitnexus-store.js`; the modal is deliberately
  NOT `webui/main.html`, which would add a stray Plugins-list "Open" button via `has_main_screen`).
- MCP registration: A0 reads `mcp_servers` (a JSON string) from settings and auto-reloads MCP when it
  CHANGES — so write the COMPLETE updated JSON via `set_settings_delta`, and don't rewrite it when
  nothing changed (see invariant 2).
- Scheduled tasks: `helpers.task_scheduler` (`TaskScheduler.get()` → `reload()` → `find_task_by_name`
  / `add_task` / `remove_task_by_uuid` → `save()`); A0 runs every ScheduledTask by feeding its prompt
  to the agent loop (no other execution path) — that's why the re-index task's only action is "run this
  command," with the real work in the deterministic helper. `ScheduledTask.check_schedule()` is a
  STATELESS ~60s cron window (no `last_run` catch-up — `job_loop` ticks 60s; setting `last_run` is a
  no-op for cron tasks); `find_task_by_name` is a SUBSTRING match (probe full names).
- Canvas auto-refresh: the bridge's `registry_watch` reloads the page when the gitnexus registry
  changes — it must watch the registry `gitnexus serve` ACTUALLY writes (`<runtime>/.gitnexus/
  registry.json`, since serve runs with `HOME=<runtime>`), NOT the bridge process's own `~/.gitnexus`
  (which is `/root/.gitnexus` and never exists). Wiring the wrong path silently disables auto-refresh.
- Config screen: A0 shows a plugin config tab IFF `webui/config.html` exists (`helpers/plugins.py`
  `has_config_screen`); `settings_sections` is separate (extra settings sections, not required). The
  panel's `config` is the saved `config.json` OR defaults (never merged) — gitnexus's `config.html`
  binds the re-index opt-in toggle to `config.reindex.enabled` (single-quoted Alpine attrs only — a raw
  `"` inside an `x-*` attr blanks the panel; verify the render in a real browser).
- Canvas gateway: `helpers.virtual_desktop.register_session(token, host, port, ...)` +
  `session_url(token)` proxy a loopback HTTP+WS service through A0's `/desktop` gateway; the gateway may
  split/merge large WS messages, so the bridge uses length-prefixed binary records (never rely on WS
  message boundaries, and avoid server→client TEXT frames).
