"""gitnexus_reindex — run the commit-aware re-index IN-PROCESS as a native A0 tool.

The scheduled "GitNexus re-index" task calls THIS tool instead of shelling out
`python3 reindex.py` through the code-execution tool. Why: A0's terminal session keeps an output
queue bound to the event loop it was created on, and a manually-run task executes on a different
event loop than the one that created the shell — so reading the command's output raised
"<Queue> is bound to a different event loop" and the run never completed. A native tool never
touches that terminal path (same pattern as vivy_curate), so it completes on both cron and a manual
Run. The blocking `gitnexus analyze` work runs OFF the event loop via asyncio.to_thread; this tool
never raises into the agent loop.
"""

import asyncio
import os

from helpers.tool import Tool, Response
from helpers import plugins

# Wall-clock cap for the whole pass (code constant, not a config knob — a wrong value just changes
# when we report "still running"; reindex.py already bounds each repo's analyze to 1800s). On
# timeout the to_thread keeps running in the background and finishes the re-index harmlessly.
RUN_DEADLINE_SECS = 1800.0


def _load_reindex():
    """Import the standalone reindex worker from whichever package path resolves (installed plugins
    live under usr.plugins.<id>; fall back to the bare name). Returns the module or None."""
    import importlib
    for name in ("usr.plugins.gitnexus.helpers.reindex",
                 "plugins.gitnexus.helpers.reindex",
                 "helpers.reindex", "reindex"):
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None


def _runtime_paths():
    """Resolve (registry_path, home) for the runtime registry that gitnexus serve/indexing uses, the
    canonical A0 way (files.get_abs_path -> usr/gitnexus-runtime, matching setup._runtime_dir). Returns
    (None, None) so run_reindex falls back to self-resolving from its own file location."""
    try:
        from helpers import files
        rt = files.get_abs_path("usr", "gitnexus-runtime")
        return os.path.join(rt, ".gitnexus", "registry.json"), rt
    except Exception:
        return None, None


class GitnexusReindex(Tool):
    async def execute(self, **kwargs):
        rx = _load_reindex()
        if rx is None or not hasattr(rx, "run_reindex"):
            return Response(message="gitnexus_reindex: re-index worker unavailable (helpers/reindex.py).",
                            break_loop=False)
        try:
            cfg = (plugins.get_plugin_config("gitnexus", self.agent) or {}).get("reindex") or {}
        except Exception:
            cfg = {}
        try:
            deadline = float(cfg.get("run_deadline_secs") or RUN_DEADLINE_SECS)
        except Exception:
            deadline = RUN_DEADLINE_SECS
        reg, home = _runtime_paths()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(rx.run_reindex, reg, home), timeout=deadline)
        except asyncio.TimeoutError:
            return Response(
                message="gitnexus_reindex: large repos are still re-indexing — it will finish in the "
                        "background.", break_loop=False)
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            return Response(message=f"gitnexus_reindex failed: {e}", break_loop=False)
        note = result.get("note") if isinstance(result, dict) else str(result)
        return Response(message=f"GitNexus re-index: {note}", break_loop=False)
