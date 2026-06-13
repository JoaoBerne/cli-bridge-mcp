"""cli-bridge — consult a council of AI CLIs from inside any MCP client."""
from importlib.metadata import PackageNotFoundError, version

try:                                            # single source of truth = pyproject (no drift)
    __version__ = version("cli-bridge-mcp")
except PackageNotFoundError:                    # running from a source tree that isn't installed
    __version__ = "0.0.0+unknown"
