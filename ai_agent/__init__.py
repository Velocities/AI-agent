"""Local AI server administration agent."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ai-agent")
except PackageNotFoundError:
    __version__ = "0+unknown"
