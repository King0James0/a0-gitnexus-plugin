"""Re-index task tool guard: in the re-index ScheduledTask's OWN context, allow ONLY gitnexus_reindex
(at most once) and response — block everything else (especially notify_user) and steer it to response.

Two failure modes this closes, both seen live:
  1. The weak model calls gitnexus_reindex 2-3x in one run (wasted re-analysis) — capped to once/cycle.
  2. The model "reports" via notify_user, which SUCCEEDS but does NOT end the turn or count as done:
     A0 and the a0_ops auto-resume watchdog treat a task chat as finished ONLY when its last tool call
     is `response`, so a notify_user-terminated turn is re-nudged and the task's own system prompt
     re-runs the re-index = an endless loop. We block notify_user (and any non-whitelisted tool) and
     tell the agent to finish with `response`.

Blocks raise RepairableException (A0 surfaces it as a warning and re-loops WITHOUT failing the task).
The once-guard self-resets each cycle (keyed on the run's user-message id). Scoped to the re-index
task's OWN context (its uuid in .reindex-task-uuid) so a normal chat / other task is never affected.
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
_TOOL = "gitnexus_reindex"


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
        name = str(tool_name or "").strip()
        if not name:
            return
        agent = self.agent
        ctx = getattr(agent, "context", None) if agent else None
        if not ctx:
            return
        task_id = _reindex_task_id()
        if not task_id or getattr(ctx, "id", None) != task_id:
            return  # only the re-index task's OWN context — never a normal chat / other task

        # `response` is the ONLY valid way to finish this task — always allow it.
        if name == "response":
            return

        if name == _TOOL:  # gitnexus_reindex — allow once per cycle, block repeats
            cur = getattr(agent, "last_user_message", None)
            run_id = str(getattr(cur, "id", "") or "")
            if _already_ran(f"gitnexus-reindex:{getattr(ctx, 'id', '')}", run_id):
                raise RepairableException(
                    "The re-index has already run in this cycle — it does not need to run again. "
                    "Finish now: call the `response` tool with the summary from the previous run. "
                    "Do not call gitnexus_reindex again."
                )
            return  # first gitnexus_reindex call this cycle — allow

        # Any other tool (notify_user, web tools, code_execution, …) is not part of this maintenance
        # task and would never reach `response` — block it and steer to response so the task completes.
        raise RepairableException(
            f"This maintenance task must not call `{name}`. Call gitnexus_reindex once (if you have not "
            "already), then FINISH by calling the `response` tool with its one-line summary. Do not use "
            "notify_user or any other tool."
        )
