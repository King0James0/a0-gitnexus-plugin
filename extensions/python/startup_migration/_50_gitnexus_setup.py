from helpers.extension import Extension
from usr.plugins.gitnexus.helpers import setup


class GitnexusSetup(Extension):
    """Runs once at framework startup. Ensures gitnexus is installed + the MCP server registered."""

    def execute(self, **kwargs):
        setup.ensure()
