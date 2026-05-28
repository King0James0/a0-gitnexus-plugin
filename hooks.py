"""Framework runtime hooks (run in /opt/venv-a0), called by the plugin installer/uninstaller.

These are declared async; A0's `call_plugin_hook` runs coroutine hooks via `asyncio.run(...)`,
which lets us drive the async task scheduler when (un)registering the scheduled re-index task.
"""


async def install():
    """Called once after the plugin is placed — install gitnexus + register the MCP server, then
    register the recurring re-index ScheduledTask.

    force=True so the server reconnects even over a stale entry (no manual MCP clearing needed).
    """
    from usr.plugins.gitnexus.helpers import setup

    setup.ensure(force=True)
    await setup.register_reindex_task()


async def uninstall():
    """Called before the plugin dir is deleted — remove the scheduled re-index task, then
    unregister the gitnexus MCP server / surface and uninstall what this plugin installed."""
    from usr.plugins.gitnexus.helpers import setup

    await setup.unregister_reindex_task()
    setup.cleanup()
