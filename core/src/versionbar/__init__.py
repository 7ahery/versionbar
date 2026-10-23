"""VersionBar core: inventories the dev tools installed on a machine."""

from importlib.metadata import version

# Package metadata is the single source of truth for name and version; nothing
# else in the repo may hard-code them.
__version__ = version("versionbar")
