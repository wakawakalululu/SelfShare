"""SelfShare -- 自建的跨主机文件夹同步（参考坚果云的同步文件夹体验）。

Modules
-------
util     hashing, atomic IO, path/ignore helpers
store    server-side content-addressed storage + SQLite metadata/history
server   HTTP sync service (stdlib only)
client   HTTP transport used by the sync engine
sync     two-way three-way-merge engine with conflict copies
watch    portable polling watcher for continuous sync
config   per-mount config and global mount registry
cli      command line interface
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
