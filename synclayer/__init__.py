from ._version import __version__
APP_NAME = "Synclayer"

_LAZY = ("Remote", "Watcher", "connect", "RemoteError", "ApiError", "SyncResult")
__all__ = ["__version__", "APP_NAME", *_LAZY]


def __getattr__(name):  # keep `import synclayer` light; load the client library on first use
    if name in _LAZY:
        from . import remote

        return getattr(remote, name)
    raise AttributeError(f"module 'synclayer' has no attribute {name!r}")
