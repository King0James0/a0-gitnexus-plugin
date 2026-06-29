"""Reconcile the (opt-in) GitNexus re-index ScheduledTask with plugin config on boot.

The task is opt-in (reindex.enabled, off by default). This boot reconcile keeps the scheduler in
sync with the saved config across container restarts: enabled -> ensure the task exists (renaming a
pre-1.2.8 "GitNexus weekly re-index" task in place); disabled -> remove it. The live UI toggle is
handled separately by the save_plugin_config hook (no restart needed). Best-effort.
"""

from helpers.extension import Extension
from usr.plugins.gitnexus.helpers import setup


class GitnexusReindexSchedule(Extension):

    def execute(self, **kwargs):
        setup.ensure_reindex()
