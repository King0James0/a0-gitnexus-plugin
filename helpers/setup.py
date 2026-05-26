"""GitNexus plugin setup (Agent Zero framework runtime, /opt/venv-a0).

Installs the `gitnexus` CLI (npm) and registers its stdio MCP server (`gitnexus mcp`)
into A0's `mcp_servers` setting. A0 auto-reloads MCP when that setting changes, so we
use `helpers.settings.set_settings_delta` rather than editing settings.json directly.

Best-effort: every entry point logs and returns instead of raising, so a setup failure
can never block A0 startup.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

PLUGIN_NAME = "gitnexus"
# Marker dropped in the plugin dir when THIS plugin installed the gitnexus CLI, so uninstall
# only removes a binary we added (never a gitnexus the user installed independently).
INSTALL_MARKER = ".installed-gitnexus"


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
    """Ensure the gitnexus CLI is on PATH; install via npm -g if missing. Returns availability."""
    if shutil.which("gitnexus"):
        return True
    npm = shutil.which("npm")
    if not npm:
        _log("npm not found in this environment; cannot install gitnexus")
        return False
    ver = str(_config().get("gitnexus_version", "latest")).strip() or "latest"
    pkg = "gitnexus" if ver == "latest" else f"gitnexus@{ver}"
    try:
        _log(f"installing {pkg} via npm -g (first run can take a minute)...")
        res = subprocess.run(
            [npm, "install", "-g", pkg], capture_output=True, text=True, timeout=600
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


def ensure(force: bool = False) -> None:
    """Install gitnexus, then register its MCP server. Best-effort.

    force=True (install hook) forces an MCP reapply so the server connects even over a stale
    entry; force=False (every boot) is idempotent and won't churn MCP.
    """
    if not ensure_binary():
        _log("gitnexus CLI unavailable; skipping MCP registration")
        return
    register_mcp(force=force)


def cleanup() -> None:
    """Uninstall: remove the MCP registration, and uninstall the gitnexus CLI if WE installed it."""
    unregister_mcp()
    _uninstall_binary_if_ours()
