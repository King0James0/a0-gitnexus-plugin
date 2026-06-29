"""Run-once guard state — exactly-once execution of a scheduled task's maintenance script per run.

A weak utility model can call the same `code_execution` (the task's `reindex.py`) several times in
one scheduled run. The guard keys "already ran" on the run's user-message id, so it self-resets each
cycle (a new run = a new message id) with no separate reset extension. State lives on `sys` so it is
shared across the (separately-imported) extension modules and survives module reloads. Pure stdlib;
unit-testable.
"""

from __future__ import annotations

import sys


def _store() -> dict:
    s = getattr(sys, "_a0_run_once", None)
    if s is None:
        s = {}
        sys._a0_run_once = s
    return s


def already_ran(key: str, run_id: str) -> bool:
    """True if `key` already ran for this `run_id` (caller should BLOCK the repeat). Otherwise mark
    it and return False (caller should ALLOW). A blank `run_id` never blocks (can't scope it)."""
    if not run_id:
        return False
    store = _store()
    if store.get(key) == run_id:
        return True
    store[key] = run_id
    return False
