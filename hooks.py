"""Framework runtime hooks (run in /opt/venv-a0), called by the plugin installer/uninstaller."""


def install():
    """Called once after the plugin is placed — install gitnexus + register the MCP server.

    force=True so the server reconnects even over a stale entry (no manual MCP clearing needed).
    """
    from usr.plugins.gitnexus.helpers import setup

    setup.ensure(force=True)


def uninstall():
    """Called before the plugin dir is deleted — unregister the gitnexus MCP server."""
    from usr.plugins.gitnexus.helpers import setup

    setup.cleanup()
