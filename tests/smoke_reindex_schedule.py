"""Smoke: _reindex_schedule maps interval/cron -> the right crontab (mocks TaskSchedule + crontab)."""
import importlib.util
import os
import sys
import types

# Mock A0's helpers.task_scheduler.TaskSchedule + python-crontab so setup.py's lazy import +
# cron-validate run offline (the real ones live in the A0 framework / the plugin's venv).
ts = types.ModuleType("helpers.task_scheduler")


class TaskSchedule:
    def __init__(self, minute, hour, day, month, weekday, timezone=None):
        self._c = f"{minute} {hour} {day} {month} {weekday}"
        self.timezone = timezone

    def to_crontab(self):
        return self._c


ts.TaskSchedule = TaskSchedule
sys.modules.setdefault("helpers", types.ModuleType("helpers"))
sys.modules["helpers.task_scheduler"] = ts

ct = types.ModuleType("crontab")


class CronTab:
    def __init__(self, crontab=None):
        if not crontab or len(crontab.split()) != 5:
            raise ValueError("bad cron")


ct.CronTab = CronTab
sys.modules["crontab"] = ct

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("gx_setup", os.path.join(_here, "..", "helpers", "setup.py"))
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)


def cron(cfg):
    return _m._reindex_schedule(cfg).to_crontab()


def test():
    assert cron({"interval": "6h"}) == "0 */6 * * *"
    assert cron({"interval": "12h"}) == "0 */12 * * *"
    assert cron({"interval": "1d"}) == "0 6 * * *"
    assert cron({"interval": "7d"}) == "0 6 * * 0"
    assert cron({"interval": "30d"}) == "0 6 1 * *"
    assert cron({}) == "0 6 * * 0", "default = weekly"
    assert cron({"interval": "bogus"}) == "0 6 * * 0", "unknown interval = weekly default"
    assert cron({"cron": "0 3 * * *", "interval": "7d"}) == "0 3 * * *", "valid custom cron overrides"
    assert cron({"cron": "not a cron", "interval": "1d"}) == "0 6 * * *", "invalid cron falls back to interval"
    print("smoke_reindex_schedule OK")


if __name__ == "__main__":
    test()
