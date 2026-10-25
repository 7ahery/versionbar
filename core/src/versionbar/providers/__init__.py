"""The built-in providers. Each is one `Provider` subclass (see `versionbar.provider`)."""

from versionbar.provider import Provider
from versionbar.providers.nvm import NvmWindows
from versionbar.providers.uv import Uv


def builtin_providers() -> list[Provider]:
    """Every built-in provider. Their installs are reported in this order, after PATH's."""
    return [NvmWindows(), Uv()]
