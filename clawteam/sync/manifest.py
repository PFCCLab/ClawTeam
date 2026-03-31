"""File manifest scanning and diff computation for sync.

Scans ``data_dir`` for syncable files, produces :class:`SyncManifest`
instances, and provides helpers for detecting changes between manifests.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterator

from clawteam.team.models import get_data_dir

# ---------------------------------------------------------------------------
# Sync scope: glob patterns relative to data_dir, keyed by directory template
# (``{team}`` is replaced at scan time).
# ---------------------------------------------------------------------------

SYNC_GLOBS: dict[str, list[str]] = {
    "tasks/{team}": ["task-*.json"],
    "teams/{team}/inboxes/*": ["msg-*.json"],
    "teams/{team}": ["config.json", "spawn_registry.json"],
    "teams/{team}/events": ["evt-*.json"],
    "sessions/{team}": ["*.json"],
    "costs/{team}": ["cost-*.json"],
    "plans/{team}": ["*.md"],
    "teams/{team}/peers": ["*.json"],
}

# Files that should never be synced (derived data, locks, temps)
_SKIP_SUFFIXES = (".lock", ".tmp")
_SKIP_NAMES = {"summary.json"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FileEntry:
    """Metadata for a single syncable file."""

    rel_path: str  # posix-style relative to data_dir
    size: int
    mtime_ns: int
    content_hash: str  # md5 hex digest


@dataclass
class SyncManifest:
    """Snapshot of all syncable files at a point in time."""

    entries: dict[str, FileEntry] = field(default_factory=dict)
    scanned_at_ns: int = 0

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "scanned_at_ns": self.scanned_at_ns,
            "entries": {
                k: {
                    "rel_path": e.rel_path,
                    "size": e.size,
                    "mtime_ns": e.mtime_ns,
                    "content_hash": e.content_hash,
                }
                for k, e in self.entries.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> SyncManifest:
        entries = {}
        for k, v in d.get("entries", {}).items():
            entries[k] = FileEntry(
                rel_path=v["rel_path"],
                size=v["size"],
                mtime_ns=v["mtime_ns"],
                content_hash=v["content_hash"],
            )
        return cls(entries=entries, scanned_at_ns=d.get("scanned_at_ns", 0))

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s: str) -> SyncManifest:
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------------


def _validate_rel_path(rel: str) -> bool:
    """Return True if *rel* is a safe relative POSIX path (no ``..``)."""
    if not rel:
        return False
    p = PurePosixPath(rel)
    if p.is_absolute():
        return False
    for part in p.parts:
        if part == "..":
            return False
    return True


def validate_rel_path(rel: str) -> str:
    """Validate and normalise *rel*; raise on unsafe input."""
    if not _validate_rel_path(rel):
        raise ValueError(f"Unsafe relative path: {rel!r}")
    return str(PurePosixPath(rel))


# ---------------------------------------------------------------------------
# Incremental scanning cache
# ---------------------------------------------------------------------------


class _ScanCache:
    """In-memory (size, mtime_ns) → hash cache to avoid redundant hashing."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[int, int, str]] = {}  # rel -> (size, mtime_ns, hash)

    def get_hash(self, rel_path: str, size: int, mtime_ns: int, path: Path) -> str:
        cached = self._cache.get(rel_path)
        if cached is not None and cached[0] == size and cached[1] == mtime_ns:
            return cached[2]
        h = _md5_file(path)
        self._cache[rel_path] = (size, mtime_ns, h)
        return h

    def prune(self, keep: set[str]) -> None:
        """Remove entries not in *keep*."""
        for k in list(self._cache):
            if k not in keep:
                del self._cache[k]


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def _iter_sync_files(data_dir: Path, team_name: str) -> Iterator[tuple[str, Path]]:
    """Yield (rel_path, abs_path) for all files matching SYNC_GLOBS."""
    for dir_template, file_patterns in SYNC_GLOBS.items():
        dir_rel = dir_template.replace("{team}", team_name)
        # If dir_template contains '*', expand via parent glob
        if "*" in dir_rel:
            parent_rel = dir_rel.rsplit("/*", 1)[0]
            parent = data_dir / parent_rel
            if not parent.exists():
                continue
            subdirs = [d for d in parent.iterdir() if d.is_dir()]
        else:
            base = data_dir / dir_rel
            if not base.exists():
                continue
            subdirs = [base]
        for subdir in subdirs:
            for pattern in file_patterns:
                for path in subdir.glob(pattern):
                    if not path.is_file():
                        continue
                    if path.suffix in _SKIP_SUFFIXES:
                        continue
                    if path.name in _SKIP_NAMES:
                        continue
                    if path.name.endswith(".consumed"):
                        continue
                    rel = path.relative_to(data_dir).as_posix()
                    yield rel, path


# Module-level scan cache — reused across calls within the same process.
_scan_cache = _ScanCache()


def scan_manifest(
    team_name: str,
    data_dir: Path | None = None,
    cache: _ScanCache | None = None,
) -> SyncManifest:
    """Scan *data_dir* and return a :class:`SyncManifest` for *team_name*."""
    if data_dir is None:
        data_dir = get_data_dir()
    if cache is None:
        cache = _scan_cache

    entries: dict[str, FileEntry] = {}
    seen: set[str] = set()

    for rel, abs_path in _iter_sync_files(data_dir, team_name):
        seen.add(rel)
        try:
            st = abs_path.stat()
        except OSError:
            continue
        h = cache.get_hash(rel, st.st_size, st.st_mtime_ns, abs_path)
        entries[rel] = FileEntry(
            rel_path=rel,
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            content_hash=h,
        )

    cache.prune(seen)
    return SyncManifest(entries=entries, scanned_at_ns=time.time_ns())


def is_syncable_path(rel_path: str, team_name: str) -> bool:
    """Return True if *rel_path* falls within SYNC_GLOBS for *team_name*."""
    if not _validate_rel_path(rel_path):
        return False
    parts = PurePosixPath(rel_path)
    name = parts.name
    if name in _SKIP_NAMES or parts.suffix in _SKIP_SUFFIXES:
        return False
    if name.endswith(".consumed"):
        return False
    for dir_template, file_patterns in SYNC_GLOBS.items():
        dir_rel = dir_template.replace("{team}", team_name)
        # Check if rel_path's parent matches the directory pattern
        parent_posix = str(parts.parent)
        # Handle wildcard directories
        if "*" in dir_rel:
            prefix = dir_rel.split("/*")[0]
            if not parent_posix.startswith(prefix + "/") and parent_posix != prefix:
                continue
        elif parent_posix != dir_rel:
            continue
        for pat in file_patterns:
            if parts.match(pat):
                return True
    return False
