"""GitNexus re-index — reset the scheduled task's context at the START of each run.

The re-index task runs in ONE dedicated context (its id = the task uuid, stored in .reindex-task-uuid)
and the scheduler REUSES that context's agent every run, appending the new prompt to the SAME
agent.history. Nothing trims it, so it grows every run until it exceeds the model window. This rebuilds
history to contain ONLY the current run's message, bounding the reused context to a single run.

MUST run at monologue_START: scheduler-driven runs never set `context.task`, so A0 never fires
`monologue_end` / `message_loop_end` for them — only `monologue_start`. Gated on the re-index context
id (.reindex-task-uuid) and the `reindex.reset_context` toggle (default on). Mirrors the github-watch
`_80` reset.
"""

import os

from helpers.extension import Extension

PLUGIN_NAME = "gitnexus"
_MARKER = ".reindex-task-uuid"


def _reindex_ctx_id() -> str:
    try:
        from helpers import files
        p = files.get_abs_path("usr", "plugins", "gitnexus", _MARKER)
    except Exception:
        p = os.path.join("/a0", "usr", "plugins", "gitnexus", _MARKER)
    try:
        return open(p, encoding="utf-8").read().strip() if os.path.isfile(p) else ""
    except Exception:
        return ""


class GitnexusReindexReset(Extension):

    async def execute(self, loop_data=None, **kwargs):
        agent = self.agent
        if not agent or getattr(agent, "number", 0) != 0:
            return
        ctx = getattr(agent, "context", None)
        rid = _reindex_ctx_id()
        if not rid or not ctx or getattr(ctx, "id", None) != rid:
            return
        try:
            from helpers import plugins
            cfg = (plugins.get_plugin_config(PLUGIN_NAME) or {}).get("reindex") or {}
        except Exception:
            cfg = {}
        if not bool(cfg.get("reset_context", True)):
            return

        cur = getattr(agent, "last_user_message", None)
        if cur is None:
            # No current message to preserve — never blank a run that has no message yet.
            return
        try:
            # Fresh history holding ONLY this run's task message; every prior run is dropped.
            new_hist = type(agent.history)(agent)
            msg = new_hist.add_message(
                getattr(cur, "ai", False), cur.content,
                tokens=getattr(cur, "tokens", 0), id=getattr(cur, "id", ""),
            )
            agent.history = new_hist
            agent.last_user_message = msg
            if loop_data is not None:
                loop_data.user_message = msg
            try:
                ctx.log.reset()
            except Exception:
                pass
        except Exception as e:
            try:
                from helpers.print_style import PrintStyle
                PrintStyle(font_color="cyan").print(f"[gitnexus] re-index context reset failed: {e}")
            except Exception:
                pass
