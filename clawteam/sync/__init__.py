"""File sync engine for HTTP-based remote agent coordination."""

from clawteam.sync.client import SyncClient, SyncLoop
from clawteam.sync.engine import SyncAction, compute_sync_plan
from clawteam.sync.manifest import FileEntry, SyncManifest, scan_manifest

__all__ = [
    "FileEntry",
    "SyncManifest",
    "SyncAction",
    "SyncClient",
    "SyncLoop",
    "compute_sync_plan",
    "scan_manifest",
]
