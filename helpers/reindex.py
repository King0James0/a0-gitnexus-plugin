#!/usr/bin/env python3
"""GitNexus plugin — scheduled commit-aware re-index worker.

Pure stdlib, no Agent Zero framework imports. Used two ways: (1) imported in-process by the native
`gitnexus_reindex` tool via `run_reindex()` — which is how the scheduled task runs it (off the event
loop, no terminal session); and (2) as a bare CLI script:

    python3 /a0/usr/plugins/gitnexus/helpers/reindex.py

Reads the gitnexus registry that `gitnexus serve`/indexing writes — the plugin's out-of-tree
runtime dir (usr/gitnexus-runtime/.gitnexus/registry.json), resolved by _resolve_runtime_registry,
NOT the process's ~/.gitnexus — and for every already-indexed git repo whose HEAD has moved since it
was last indexed, runs an incremental `gitnexus analyze`. "Refresh changed only" — we never discover
or index new repos; we only keep current what the user already chose to index.

Skipped: repos whose HEAD is unchanged, repos that aren't git work-trees, repos whose
path is gone, and repos indexed without git tracking (empty `lastCommit`).
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys

# clean_env: least-privilege env for the `gitnexus analyze` child — it must NOT inherit A0's runtime
# secrets. This is a standalone script (run via subprocess by a scheduled task), so the sibling import
# may not resolve; the multi-name shim tries it and falls back to an identical inline allowlist.
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

LOG_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reindex.log")
)


def _resolve_runtime_registry() -> tuple:
    """Resolve (registry_path, home) for the registry that `gitnexus serve`/indexing actually uses.

    gitnexus runs with HOME set to the plugin's out-of-tree runtime dir (usr/gitnexus-runtime; see
    setup._runtime_dir + ensure_serving), so its registry lives at <runtime>/.gitnexus/registry.json
    — NOT the calling process's ~/.gitnexus, which for A0 is /root/.gitnexus and is always empty (that
    mismatch is why a manual re-index reported "no indexed repos" right after a repo was indexed).
    Resolve the runtime dir WITHOUT importing Agent Zero: prefer $GITNEXUS_RUNTIME, else derive it from
    this file's location (usr/plugins/gitnexus/helpers/reindex.py -> usr/gitnexus-runtime). Fall back to
    ~ only if neither resolves to an existing dir."""
    rt = os.environ.get("GITNEXUS_RUNTIME") or ""
    if not rt:
        here = os.path.dirname(os.path.abspath(__file__))                       # usr/plugins/gitnexus/helpers
        rt = os.path.normpath(os.path.join(here, "..", "..", "..", "gitnexus-runtime"))  # usr/gitnexus-runtime
    if os.path.isdir(rt):
        return os.path.join(rt, ".gitnexus", "registry.json"), rt
    return os.path.expanduser("~/.gitnexus/registry.json"), os.path.expanduser("~")


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str) -> None:
    line = f"[{_ts()}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _load_registry(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        _log(f"could not read registry {path}: {e}")
        return []
    return data if isinstance(data, list) else []


def _is_git_worktree(path: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False


def _head(path: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def run_reindex(registry_path: str | None = None, home: str | None = None) -> dict:
    """Refresh-changed-only re-index. Returns a summary dict: {refreshed, skipped, fail, note}.

    registry_path/home default to the gitnexus RUNTIME registry (where serve/indexing writes — see
    _resolve_runtime_registry), NOT ~/.gitnexus; `gitnexus analyze` runs with HOME=home so it updates
    that same registry. The native `gitnexus_reindex` tool passes the canonical A0-resolved paths; the
    CLI / a bare call self-resolves from this file's location.

    Pure stdlib + subprocess, so it is safe to call IN-PROCESS — the tool runs it off the event loop
    (avoiding A0's terminal session, whose loop-bound output queue raises "Queue is bound to a different
    event loop" on a manually-run task). Never raises (per-repo try/except + bounded timeouts)."""
    if registry_path is None or home is None:
        reg, rt = _resolve_runtime_registry()
        registry_path = registry_path or reg
        home = home or rt
    gx = shutil.which("gitnexus")
    if not gx:
        note = "gitnexus CLI not on PATH; nothing to do"
        _log(note)
        return {"refreshed": 0, "skipped": 0, "fail": 0, "note": note}

    entries = _load_registry(registry_path)
    if not entries:
        note = f"no indexed repos in registry ({registry_path}); nothing to do"
        _log(note)
        return {"refreshed": 0, "skipped": 0, "fail": 0, "note": note}

    refreshed = skipped = fail = 0
    for entry in entries:
        name = entry.get("name") or "?"
        path = entry.get("path") or ""
        last = (entry.get("lastCommit") or "").strip()
        try:
            if not last:
                skipped += 1  # indexed without git tracking (--skip-git / non-git)
                continue
            if not path or not os.path.isdir(path) or not _is_git_worktree(path):
                _log(f"skip {name}: path missing or not a git work-tree ({path})")
                skipped += 1
                continue
            head = _head(path)
            if head is None:
                _log(f"skip {name}: could not read HEAD")
                skipped += 1
                continue
            if head == last:
                skipped += 1
                continue
            _log(f"re-index {name}: {last[:7]} -> {head[:7]}")
            r = subprocess.run(
                [gx, "analyze", path, "--skip-agents-md", "--name", name],
                env=clean_env(extra={"HOME": home}),  # write back to the SAME runtime registry
                capture_output=True, text=True, timeout=1800,
            )
            if r.returncode == 0:
                refreshed += 1
            else:
                fail += 1
                _log(f"FAILED {name}: rc={r.returncode} {(r.stderr or r.stdout).strip()[:300]}")
        except Exception as e:
            fail += 1
            _log(f"FAILED {name}: {e}")

    note = f"done: refreshed={refreshed} skipped={skipped} fail={fail}"
    _log(note)
    return {"refreshed": refreshed, "skipped": skipped, "fail": fail, "note": note}


def main() -> int:
    run_reindex()
    return 0


if __name__ == "__main__":
    sys.exit(main())
