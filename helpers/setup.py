"""GitNexus plugin setup (Agent Zero framework runtime, /opt/venv-a0).

Installs the `gitnexus` CLI (npm) and registers its stdio MCP server (`gitnexus mcp`)
into A0's `mcp_servers` setting. A0 auto-reloads MCP when that setting changes, so we
use `helpers.settings.set_settings_delta` rather than editing settings.json directly.

Best-effort: every entry point logs and returns instead of raising, so a setup failure
can never block A0 startup.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

PLUGIN_NAME = "gitnexus"

# clean_env: least-privilege env for spawned children (gitnexus CLI, headless chromium) — they must
# NOT inherit A0's runtime secrets. Multi-name shim + inline fallback (identical allowlist) so a
# missing import can't re-leak or break.
clean_env = None  # type: ignore[assignment]
for _se_name in ("usr.plugins.gitnexus.helpers.secure_env",
                 "plugins.gitnexus.helpers.secure_env",
                 "helpers.secure_env", "secure_env"):
    try:
        import importlib
        clean_env = importlib.import_module(_se_name).clean_env  # type: ignore
        break
    except Exception:  # pragma: no cover
        continue
if clean_env is None:  # pragma: no cover - import fallback; identical to secure_env.clean_env
    def clean_env(extra=None, *, allow=(), proxy=True):  # type: ignore[misc]
        _k = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE",
              "TZ", "DISPLAY", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "XDG_CACHE_HOME",
              "XDG_DATA_HOME", "TMPDIR", "TMP", "TEMP"} | set(allow)
        if proxy:
            _k |= {"HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY",
                   "http_proxy", "https_proxy", "ftp_proxy", "all_proxy", "no_proxy"}
        _e = {k: os.environ[k] for k in _k if k in os.environ}
        if extra:
            _e.update({k: v for k, v in extra.items() if v is not None})
        return _e

# Marker dropped in the plugin dir when THIS plugin installed the gitnexus CLI, so uninstall
# only removes a binary we added (never a gitnexus the user installed independently).
INSTALL_MARKER = ".installed-gitnexus"
# Canvas surface (route 2 — screencast). The gitnexus web UI is a LOCAL-only SPA: it connects to
# its server at a hardcoded `localhost:4747` over Server-Sent Events, browser-side. That can't be
# iframed from a remote browser (localhost = the user's machine) and A0's gateway can't carry SSE.
# So we render the SPA in a headless chromium INSIDE the container (where localhost:4747 works) and
# CDP-screencast it to the canvas via the shared bridge (helpers/screencast.py) — only pixels cross
# the gateway (over its WS path). The surface id/token:
SURFACE_TOKEN = "gitnexus"
INSTALL_MARKER_CHROME = ".installed-gitnexus-chromium"  # set if WE apt-installed chromium

# Scheduled commit-aware re-index. Registered as an A0 ScheduledTask on install (visible/editable
# in the scheduler UI) that just runs helpers/reindex.py. The task's uuid is stored in a marker so
# uninstall can remove it even if the user renamed it in the UI.
REINDEX_TASK_NAME = "GitNexus weekly re-index"
REINDEX_TASK_MARKER = ".reindex-task-uuid"


def _log(msg: str) -> None:
    try:
        from helpers.print_style import PrintStyle

        PrintStyle(font_color="cyan").print(f"[{PLUGIN_NAME}] {msg}")
    except Exception:
        print(f"[{PLUGIN_NAME}] {msg}")


def _plugin_dir() -> str:
    from helpers import files

    return files.get_abs_path("usr", "plugins", PLUGIN_NAME)


def _config() -> dict:
    """Merged plugin config, falling back to default_config.yaml."""
    try:
        from helpers import plugins

        cfg = plugins.get_plugin_config(PLUGIN_NAME)
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    try:
        from helpers import files, yaml as yaml_helper
        import os

        path = os.path.join(_plugin_dir(), "default_config.yaml")
        if files.exists(path):
            loaded = yaml_helper.loads(files.read_file(path))
            if isinstance(loaded, dict):
                return loaded
    except Exception:
        pass
    return {}


def _server_name(cfg: dict | None = None) -> str:
    return (cfg if cfg is not None else _config()).get("mcp_server_name") or "gitnexus"


def ensure_binary() -> bool:
    """Ensure the gitnexus CLI is on PATH; install via npm -g if missing. Returns availability.

    We install with ONNXRUNTIME_NODE_INSTALL=skip. gitnexus depends on `onnxruntime-node` only for
    its optional `--embeddings` feature (which this plugin never uses), and that dependency's native
    installer downloads a NuGet runtime that fails to unpack in some environments — which would
    abort the whole `npm i -g` and leave no binary. onnxruntime-node's own documented skip switch
    makes its install step exit early, so the REQUIRED native deps still build normally (the
    @ladybugdb graph engine — without which `gitnexus serve`/`analyze` crash — and the tree-sitter
    grammars), and the MCP server, analysis, and the Canvas surface all work."""
    if shutil.which("gitnexus"):
        return True
    npm = shutil.which("npm")
    if not npm:
        _log("npm not found in this environment; cannot install gitnexus")
        return False
    ver = str(_config().get("gitnexus_version", "latest")).strip() or "latest"
    pkg = "gitnexus" if ver == "latest" else f"gitnexus@{ver}"
    env = {**os.environ, "ONNXRUNTIME_NODE_INSTALL": "skip"}
    try:
        _log(f"installing {pkg} via npm -g (onnx embeddings skipped; first run can take a minute)...")
        res = subprocess.run(
            [npm, "install", "-g", pkg], capture_output=True, text=True, timeout=600, env=env
        )
        if res.returncode != 0:
            _log("npm install failed: " + (res.stderr.strip() or res.stdout.strip())[:300])
    except Exception as e:
        _log(f"npm install error: {e}")
    ok = shutil.which("gitnexus") is not None
    if ok:
        # record that WE installed it, so uninstall can remove it (and only it)
        try:
            with open(os.path.join(_plugin_dir(), INSTALL_MARKER), "w") as f:
                f.write("gitnexus installed by the gitnexus plugin\n")
        except Exception:
            pass
    return ok


def _uninstall_binary_if_ours() -> None:
    """npm-uninstall gitnexus ONLY if this plugin installed it (marker present)."""
    marker = os.path.join(_plugin_dir(), INSTALL_MARKER)
    if not os.path.exists(marker):
        return  # we didn't install it — leave the user's gitnexus alone
    npm = shutil.which("npm")
    if npm and shutil.which("gitnexus"):
        try:
            _log("uninstalling gitnexus CLI (installed by this plugin)...")
            subprocess.run(
                [npm, "uninstall", "-g", "gitnexus"], capture_output=True, text=True, timeout=300
            )
        except Exception as e:
            _log(f"npm uninstall error: {e}")
    try:
        os.remove(marker)
    except Exception:
        pass


def _read_mcp_config() -> dict:
    """Current mcp_servers setting as a dict with an 'mcpServers' map."""
    from helpers import settings as settings_helper

    raw = ""
    try:
        s = settings_helper.get_settings()
        raw = s.get("mcp_servers", "") if isinstance(s, dict) else getattr(s, "mcp_servers", "")
    except Exception as e:
        _log(f"could not read settings: {e}")
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("mcpServers", {})
    return data


def register_mcp(force: bool = False) -> None:
    """Add the gitnexus stdio MCP server to A0 settings.

    Idempotent on boot (force=False: skip if already registered, so MCP isn't reloaded every
    boot). On install (force=True): force a reapply so a freshly-installed server connects even
    if an identical stale entry already exists (e.g. left over from a prior manual delete) —
    A0 only reconnects when the mcp_servers value changes, so we drop-then-re-add the entry.
    """
    from helpers import settings as settings_helper

    name = _server_name()
    data = _read_mcp_config()
    existing = data["mcpServers"].get(name)
    already = isinstance(existing, dict) and existing.get("command") == "gitnexus"
    if already and not force:
        return  # already registered; don't churn the MCP reload each boot
    entry = {
        "type": "stdio",
        "command": "gitnexus",
        "args": ["mcp"],
        "env": {},
        "description": "GitNexus code-graph queries",
    }
    try:
        if force and already:
            # the entry is unchanged, so nudge A0 to reconnect: write it out without gitnexus
            # first (a real change -> reload), then add it back (another change -> reconnect)
            without = json.loads(json.dumps(data))
            without["mcpServers"].pop(name, None)
            settings_helper.set_settings_delta({"mcp_servers": json.dumps(without, indent=4)})
        data["mcpServers"][name] = entry
        settings_helper.set_settings_delta({"mcp_servers": json.dumps(data, indent=4)})
        _log(f"registered MCP server '{name}'" + (" (forced reapply)" if force else ""))
    except Exception as e:
        _log(f"could not register MCP server: {e}")


def unregister_mcp() -> None:
    """Remove the gitnexus MCP server from A0 settings (triggers MCP reload)."""
    from helpers import settings as settings_helper

    name = _server_name()
    data = _read_mcp_config()
    if name in data.get("mcpServers", {}):
        data["mcpServers"].pop(name, None)
        try:
            settings_helper.set_settings_delta({"mcp_servers": json.dumps(data, indent=4)})
            _log(f"unregistered MCP server '{name}'")
        except Exception as e:
            _log(f"could not unregister MCP server: {e}")


# --- Canvas surface (route 2: gitnexus serve + headless chromium + CDP screencast bridge) --------

def _runtime_dir() -> str:
    # Out of the plugin folder on purpose: A0 watches plugin roots recursively, and the headless
    # Chromium profile + logs under here churn the filesystem constantly. Kept inside the plugin
    # dir, that churn could trip A0's startup watchdog registration into a deadlock. Living under
    # usr/ (persistent volume, NOT a watched plugin root) keeps the canvas session across restarts;
    # cleanup() removes it on uninstall.
    from helpers import files

    return files.get_abs_path("usr", f"{PLUGIN_NAME}-runtime")


def _migrate_legacy_runtime() -> None:
    """One-time move of a pre-1.2.5 runtime dir from inside the (recursively watched) plugin
    folder to the out-of-tree location, so the Chromium profile/session carries over. Best-effort."""
    try:
        legacy = os.path.join(_plugin_dir(), "runtime")
        new = _runtime_dir()
        if os.path.isdir(legacy) and not os.path.exists(new):
            os.makedirs(os.path.dirname(new), exist_ok=True)
            shutil.move(legacy, new)
            _log(f"migrated runtime dir out of the plugin folder -> {new}")
        # a stray pre-1.2.5 serve.log also lived in the plugin dir; it's now written under runtime/
        legacy_log = os.path.join(_plugin_dir(), "serve.log")
        if os.path.isfile(legacy_log):
            os.remove(legacy_log)
    except Exception as e:
        _log(f"runtime migration skipped: {e}")


def _serve_port(cfg: dict | None = None) -> int:
    try:
        return int((cfg if cfg is not None else _config()).get("serve_port") or 4747)
    except Exception:
        return 4747


def _cdp_port(cfg: dict | None = None) -> int:
    try:
        return int((cfg if cfg is not None else _config()).get("cdp_port") or 9223)
    except Exception:
        return 9223


def _bridge_port(cfg: dict | None = None) -> int:
    try:
        return int((cfg if cfg is not None else _config()).get("bridge_port") or 14601)
    except Exception:
        return 14601


def _chrome_path() -> str | None:
    """Find a Chromium/Chrome to render the SPA: a system browser, else a Playwright cache build."""
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        p = shutil.which(name)
        if p:
            return p
    for pat in (
        "/root/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux/chrome"),
    ):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


def ensure_chromium() -> str | None:
    """Return a chromium path; if none and apt is available, best-effort install one (marker-tracked
    so uninstall only removes a browser WE added). The renderer needs a real Chromium."""
    p = _chrome_path()
    if p:
        return p
    if shutil.which("apt-get"):
        try:
            _log("installing chromium for the Canvas graph view (first run)...")
            subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=300)
            subprocess.run(
                ["apt-get", "install", "-y", "chromium"], capture_output=True, text=True, timeout=900,
                env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
            )
        except Exception as e:
            _log(f"chromium install error: {e}")
        p = _chrome_path()
        if p:
            try:
                open(os.path.join(_plugin_dir(), INSTALL_MARKER_CHROME), "w").write("chromium installed by the gitnexus plugin\n")
            except Exception:
                pass
    if not p:
        _log("no chromium available; the Canvas graph view needs one (the MCP tools still work)")
    return p


def _http_ready(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _proc_running(pattern: str) -> bool:
    try:
        return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0
    except Exception:
        return False


def ensure_serving(cfg: dict | None = None) -> bool:
    """Start `gitnexus serve` if it isn't already answering on the port. Idempotent (HTTP probe)."""
    cfg = cfg if cfg is not None else _config()
    port = _serve_port(cfg)
    if _http_ready(port):
        return True
    gx = shutil.which("gitnexus")
    if not gx:
        return False
    try:
        rt = _runtime_dir()
        os.makedirs(rt, exist_ok=True)
        log = open(os.path.join(rt, "serve.log"), "ab")
        subprocess.Popen(
            [gx, "serve", "--port", str(port), "--host", "127.0.0.1"],
            env=clean_env(extra={"HOME": rt}),
            stdout=log, stderr=log, start_new_session=True,
        )
    except Exception as e:
        _log(f"could not start `gitnexus serve`: {e}")
        return False
    for _ in range(40):  # cold start; wait until it serves HTTP
        if _http_ready(port):
            return True
        time.sleep(0.5)
    return False


def _renderer_match(cfg: dict) -> str:
    return f"remote-debugging-port={_cdp_port(cfg)}"


def _relaunch_spec_path() -> str:
    return os.path.join(_runtime_dir(), "relaunch.json")


def launch_renderer(cfg: dict) -> bool:
    """Launch a headless Chromium pointed at the local gitnexus web UI, with CDP enabled, so the
    bridge can screencast it. Idempotent (matches the --remote-debugging-port cmdline). Leaves a
    relaunch spec so the bridge's watchdog can resurrect it if it dies."""
    if _proc_running(_renderer_match(cfg)):
        return True
    chrome = ensure_chromium()
    if not chrome:
        return False
    rt = _runtime_dir()
    udir = os.path.join(rt, "chrome")
    os.makedirs(udir, exist_ok=True)
    for lock in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            os.remove(os.path.join(udir, lock))
        except Exception:
            pass
    # --enable-unsafe-swiftshader: render WebGL graph views under headless/no-gpu instead of blanking.
    argv = [
        chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--enable-unsafe-swiftshader",
        f"--remote-debugging-port={_cdp_port(cfg)}", f"--user-data-dir={udir}",
        "--window-size=1440,900", "--disable-dev-shm-usage",
        f"http://localhost:{_serve_port(cfg)}/",
    ]
    env = clean_env(extra={"HOME": rt})
    try:
        spec = {"argv": argv, "env": {k: str(v) for k, v in env.items()},
                "cfg_dir": udir, "log": os.path.join(rt, "chrome.log"),
                "proc_match": _renderer_match(cfg)}
        os.makedirs(rt, exist_ok=True)
        with open(_relaunch_spec_path(), "w") as f:
            json.dump(spec, f)
        log = open(os.path.join(rt, "chrome.log"), "ab")
        subprocess.Popen(argv, env=env, stdout=log, stderr=log, start_new_session=True, cwd=rt)
    except Exception as e:
        _log(f"could not launch the graph renderer: {e}")
        return False
    for _ in range(40):  # wait for CDP to come up
        if _http_ready(_cdp_port(cfg)):
            return True
        time.sleep(0.5)
    return _proc_running(_renderer_match(cfg))


def _bridge_running(cfg: dict) -> bool:
    return _proc_running(f"screencast.py --cdp-port {_cdp_port(cfg)}")


def launch_bridge(cfg: dict) -> bool:
    """Start the CDP screencast bridge (binary frames + input + reconnect + renderer watchdog)."""
    port = _bridge_port(cfg)
    if _bridge_running(cfg):
        return _http_ready(port)
    rt = _runtime_dir()
    os.makedirs(rt, exist_ok=True)
    try:
        bridge = os.path.join(_plugin_dir(), "helpers", "screencast.py")
        registry = os.path.expanduser("~/.gitnexus/registry.json")
        log = open(os.path.join(rt, "screencast.log"), "ab")
        subprocess.Popen(
            [sys.executable, bridge, "--cdp-port", str(_cdp_port(cfg)),
             "--listen-host", "127.0.0.1", "--listen-port", str(port),
             "--relaunch-spec", _relaunch_spec_path(),
             "--reload-on-change", registry],
            stdout=log, stderr=log, start_new_session=True, cwd=rt,
        )
    except Exception as e:
        _log(f"could not start the screencast bridge: {e}")
        return False
    for _ in range(40):
        if _http_ready(port):
            return True
        time.sleep(0.5)
    return False


def start_surface_session(cfg: dict | None = None) -> str | None:
    """Ensure gitnexus + its web server + the headless renderer + the screencast bridge are up,
    register the bridge with A0's virtual-desktop gateway, and return the proxied surface URL.
    Idempotent. Runs in the web-server process so register_session lands in the in-process registry."""
    cfg = cfg if cfg is not None else _config()
    if not ensure_binary():
        return None
    if not ensure_serving(cfg):
        return None
    if not launch_renderer(cfg):
        return None
    if not launch_bridge(cfg):
        return None
    try:
        from helpers import virtual_desktop

        virtual_desktop.register_session(
            token=SURFACE_TOKEN, host="127.0.0.1", port=_bridge_port(cfg),
            owner="gitnexus", title="GitNexus",
        )
        return virtual_desktop.session_url(SURFACE_TOKEN, title="GitNexus")
    except Exception as e:
        _log(f"could not register the GitNexus surface session: {e}")
        return None


def stop_surface_session(cfg: dict | None = None) -> None:
    """Stop the surface (unregister the gateway session). The serve/renderer/bridge are left
    running — idle/cheap and makes re-open instant; cleanup() stops everything on uninstall."""
    try:
        from helpers import virtual_desktop

        virtual_desktop.unregister_session(SURFACE_TOKEN)
    except Exception:
        pass


# --- Scheduled re-index task (register on install, remove on uninstall) -------------------------

def _reindex_marker_path() -> str:
    return os.path.join(_plugin_dir(), REINDEX_TASK_MARKER)


def _write_reindex_marker(uuid: str) -> None:
    try:
        with open(_reindex_marker_path(), "w") as f:
            f.write(uuid)
    except Exception:
        pass


def _read_reindex_marker() -> str:
    try:
        with open(_reindex_marker_path()) as f:
            return f.read().strip()
    except Exception:
        return ""


def _delete_reindex_marker() -> None:
    try:
        os.remove(_reindex_marker_path())
    except Exception:
        pass


async def register_reindex_task() -> None:
    """Register the recurring re-index ScheduledTask (idempotent). Runs only on install, so a user
    who edits the schedule or deletes the task keeps their choice. Best-effort: logs, never raises."""
    cfg = _config().get("reindex") or {}
    if not cfg.get("enabled", True):
        return
    try:
        from helpers.task_scheduler import TaskScheduler, ScheduledTask, TaskSchedule
    except Exception as e:
        _log(f"scheduler unavailable; skipping re-index task: {e}")
        return
    try:
        sched = TaskScheduler.get()
        await sched.reload()
        if sched.find_task_by_name(REINDEX_TASK_NAME):
            # already present (e.g. double install) — point the marker at it and stop
            existing = sched.find_task_by_name(REINDEX_TASK_NAME)[0]
            _write_reindex_marker(existing.uuid)
            return
        sc = cfg.get("schedule") or {}
        schedule = TaskSchedule(
            minute=str(sc.get("minute", "0")),
            hour=str(sc.get("hour", "6")),
            day=str(sc.get("day", "*")),
            month=str(sc.get("month", "*")),
            weekday=str(sc.get("weekday", "0")),
        )
        tz = (cfg.get("timezone") or "").strip() or None
        helper = os.path.join(_plugin_dir(), "helpers", "reindex.py")
        task = ScheduledTask.create(
            name=REINDEX_TASK_NAME,
            system_prompt=(
                "You are a maintenance task runner. Run exactly the command in the message using "
                "the code execution tool (terminal runtime), then report only its final summary "
                "line. Take no other actions and ask no questions."
            ),
            prompt=f"Run this command and report its output:\n\npython3 {helper}",
            schedule=schedule,
            timezone=tz,
        )
        await sched.add_task(task)
        await sched.save()
        _write_reindex_marker(task.uuid)
        _log(f"registered scheduled re-index task ({schedule.to_crontab()})")
    except Exception as e:
        _log(f"could not register re-index task: {e}")


async def unregister_reindex_task() -> None:
    """Remove the re-index ScheduledTask (by stored uuid, falling back to name) and drop the
    marker. Best-effort: logs, never raises."""
    try:
        from helpers.task_scheduler import TaskScheduler
    except Exception:
        _delete_reindex_marker()
        return
    try:
        sched = TaskScheduler.get()
        await sched.reload()
        uuid = _read_reindex_marker()
        removed = False
        if uuid:
            await sched.remove_task_by_uuid(uuid)
            removed = True
        elif sched.find_task_by_name(REINDEX_TASK_NAME):
            await sched.remove_task_by_name(REINDEX_TASK_NAME)
            removed = True
        if removed:
            await sched.save()
            _log("removed scheduled re-index task")
    except Exception as e:
        _log(f"could not remove re-index task: {e}")
    finally:
        _delete_reindex_marker()


def ensure(force: bool = False) -> None:
    """Install gitnexus and register its MCP server. (The Canvas surface — serve + headless
    renderer + bridge — starts lazily when the user opens it, not at boot.)

    force=True (install hook) forces an MCP reapply so the server connects even over a stale
    entry; force=False (every boot) is idempotent and won't churn MCP.
    """
    _migrate_legacy_runtime()
    if not ensure_binary():
        _log("gitnexus CLI unavailable; skipping MCP registration")
        return
    register_mcp(force=force)


def cleanup() -> None:
    """Uninstall: unregister MCP + the surface session, stop the bridge/renderer/serve, and
    uninstall the gitnexus CLI (and chromium) if WE installed them."""
    unregister_mcp()
    cfg = _config()
    try:
        from helpers import virtual_desktop

        virtual_desktop.unregister_session(SURFACE_TOKEN)
    except Exception:
        pass
    for pat in (f"screencast.py --cdp-port {_cdp_port(cfg)}", _renderer_match(cfg), "gitnexus serve"):
        try:
            subprocess.run(["pkill", "-f", pat], capture_output=True, timeout=15)
        except Exception:
            pass
    # uninstall chromium only if WE apt-installed it
    marker_chrome = os.path.join(_plugin_dir(), INSTALL_MARKER_CHROME)
    if os.path.exists(marker_chrome) and shutil.which("apt-get"):
        try:
            subprocess.run(["apt-get", "purge", "-y", "chromium"], capture_output=True, text=True,
                           timeout=300, env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
        except Exception:
            pass
        try:
            os.remove(marker_chrome)
        except Exception:
            pass
    _uninstall_binary_if_ours()
    # remove the out-of-tree runtime dir (regenerable canvas state — Chromium profile, logs)
    try:
        shutil.rmtree(_runtime_dir(), ignore_errors=True)
    except Exception:
        pass
