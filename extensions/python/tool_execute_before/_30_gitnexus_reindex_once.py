"""Exactly-once: block a repeat run of reindex.py within one scheduled re-index run.

The re-index ScheduledTask's agent runs `python3 .../reindex.py`. A weak utility model sometimes
calls it 2-3x in the same run — wasted re-analysis. This guard lets it run once per run and short-
circuits repeats with a RepairableException (A0 surfaces it as a warning and re-loops WITHOUT
failing the task, so the agent reports the result it already has and finishes). Self-resets each
cycle (keyed on the run's user-message id). Scoped to the re-index task's OWN context (its uuid,
stored in .reindex-task-uuid) so a manual `reindex.py` run in a normal chat is never affected.
Always on (no config knob).
"""

from __future__ import annotations

import os

from helpers.errors import RepairableException
from helpers.extension import Extension

# run-once store: multi-name shim + inline fallback so a missing import can't break the guard.
_already_ran = None  # type: ignore[assignment]
for _ro_name in ("usr.plugins.gitnexus.helpers.run_once",
                 "plugins.gitnexus.helpers.run_once",
                 "helpers.run_once", "run_once"):
    try:
        import importlib
        _already_ran = importlib.import_module(_ro_name).already_ran  # type: ignore
        break
    except Exception:  # pragma: no cover
        continue
if _already_ran is None:  # pragma: no cover - identical to run_once.already_ran
    import sys as _sys

    def _already_ran(key, run_id):  # type: ignore[misc]
        if not run_id:
            return False
        s = getattr(_sys, "_a0_run_once", None)
        if s is None:
            s = {}
            _sys._a0_run_once = s
        if s.get(key) == run_id:
            return True
        s[key] = run_id
        return False

_MARKER = ".reindex-task-uuid"
_SCRIPT = "reindex.py"


def _reindex_task_id() -> str:
    try:
        from helpers import files
        p = files.get_abs_path("usr", "plugins", "gitnexus", _MARKER)
    except Exception:
        p = os.path.join("/a0", "usr", "plugins", "gitnexus", _MARKER)
    try:
        return open(p, encoding="utf-8").read().strip() if os.path.isfile(p) else ""
    except Exception:
        return ""


class GitnexusReindexOnce(Extension):

    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs):
        if str(tool_name or "").strip() != "code_execution_tool":
            return
        agent = self.agent
        ctx = getattr(agent, "context", None) if agent else None
        if not ctx:
            return
        task_id = _reindex_task_id()
        if not task_id or getattr(ctx, "id", None) != task_id:
            return  # only the re-index task's own context — never a normal chat
        code = str(tool_args.get("code") or "") if isinstance(tool_args, dict) else ""
        if _SCRIPT not in code:
            return
        cur = getattr(agent, "last_user_message", None)
        run_id = str(getattr(cur, "id", "") or "")
        if _already_ran(f"gitnexus-reindex:{getattr(ctx, 'id', '')}", run_id):
            raise RepairableException(
                "The re-index has already run in this cycle — it does not need to run again. "
                "Report the result from the previous run with the `response` tool and finish. "
                "Do not run reindex.py again."
            )
