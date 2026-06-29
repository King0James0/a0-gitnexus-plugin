"""Smoke test: run_once.already_ran — exactly-once-per-run gating (pure stdlib)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from helpers import run_once  # noqa: E402


def test():
    # reset shared store so reruns are deterministic
    if hasattr(sys, "_a0_run_once"):
        delattr(sys, "_a0_run_once")

    # fresh run: first call allows (False); repeats in the SAME run block (True)
    assert run_once.already_ran("reindex:ctx1", "run-A") is False, "first call must allow"
    assert run_once.already_ran("reindex:ctx1", "run-A") is True, "repeat in same run must block"
    assert run_once.already_ran("reindex:ctx1", "run-A") is True, "still blocked"

    # new run (new message id) -> allowed again, then blocks on repeat
    assert run_once.already_ran("reindex:ctx1", "run-B") is False, "new run must allow"
    assert run_once.already_ran("reindex:ctx1", "run-B") is True, "repeat in new run must block"

    # different context, same run id -> independent
    assert run_once.already_ran("reindex:ctx2", "run-B") is False, "different ctx is independent"

    # blank run id never blocks (can't scope it)
    assert run_once.already_ran("reindex:ctx3", "") is False
    assert run_once.already_ran("reindex:ctx3", "") is False, "blank run id never blocks"

    print("smoke_run_once OK")


if __name__ == "__main__":
    test()
