#!/usr/bin/env python3
"""GitNexus plugin — scheduled commit-aware re-index worker.

Pure stdlib, no Agent Zero framework imports (it runs as a bare script via the agent's
code-execution tool):

    python3 /a0/usr/plugins/gitnexus/helpers/reindex.py

Reads the gitnexus registry (~/.gitnexus/registry.json) and, for every already-indexed
git repo whose HEAD has moved since it was last indexed, runs an incremental
`gitnexus analyze`. "Refresh changed only" — we never discover or index new repos; we
only keep current what the user already chose to index.

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

REGISTRY = os.path.expanduser("~/.gitnexus/registry.json")
LOG_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reindex.log")
)


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


def _load_registry() -> list:
    try:
        with open(REGISTRY, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        _log(f"could not read registry {REGISTRY}: {e}")
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


def main() -> int:
    gx = shutil.which("gitnexus")
    if not gx:
        _log("gitnexus CLI not on PATH; nothing to do")
        return 0

    entries = _load_registry()
    if not entries:
        _log("no indexed repos in registry; nothing to do")
        return 0

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
                env=clean_env(extra={"HOME": os.path.expanduser("~")}),
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

    _log(f"done: refreshed={refreshed} skipped={skipped} fail={fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
