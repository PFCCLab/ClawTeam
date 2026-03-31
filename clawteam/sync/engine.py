"""Three-way merge engine for file sync.

Computes a list of :class:`SyncAction` items by comparing a local manifest,
a remote manifest, and the *last_synced* snapshot (the state right after the
previous successful sync).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from clawteam.sync.manifest import SyncManifest


@dataclass
class SyncAction:
    """A single file-level action to reconcile local and remote."""

    rel_path: str
    direction: str  # "push" | "pull"
    reason: str  # "new" | "updated" | "deleted"


# ---------------------------------------------------------------------------
# Conflict resolution
# ---------------------------------------------------------------------------

# File-type → winner when both sides changed
_LEADER_WINS = {"config.json", "spawn_registry.json"}


def _resolve_conflict(rel_path: str, local_data: bytes | None, remote_data: bytes | None) -> str:
    """Return ``"push"`` or ``"pull"`` for a true conflict.

    Strategy per file type:
    * ``task-*.json``: compare ``updated_at`` — later timestamp wins.
    * ``config.json`` / ``spawn_registry.json``: leader wins (push).
    * ``sessions/*.json`` / ``plans/*.md``: remote wins (pull).
    * ``msg-*.json`` / ``evt-*.json`` / ``cost-*.json``: should never
      conflict (unique filenames), but default to remote wins.
    """
    name = rel_path.rsplit("/", 1)[-1] if "/" in rel_path else rel_path

    # Leader-managed files
    if name in _LEADER_WINS:
        return "push"

    # Task files: last-write-wins
    if name.startswith("task-") and name.endswith(".json"):
        return _last_write_wins(local_data, remote_data)

    # Agent-owned files (sessions, plans)
    if "/sessions/" in rel_path or "/plans/" in rel_path:
        return "pull"

    # Everything else: default remote wins
    return "pull"


def _last_write_wins(local_data: bytes | None, remote_data: bytes | None) -> str:
    """Compare ``updated_at`` in JSON payloads; later writer wins."""
    local_ts = _extract_updated_at(local_data)
    remote_ts = _extract_updated_at(remote_data)
    if local_ts and remote_ts:
        return "push" if local_ts >= remote_ts else "pull"
    # If we can't compare, remote wins
    return "pull"


def _extract_updated_at(data: bytes | None) -> str:
    if not data:
        return ""
    try:
        obj = json.loads(data)
        return obj.get("updated_at") or obj.get("updatedAt") or ""
    except (json.JSONDecodeError, ValueError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Core diff algorithm
# ---------------------------------------------------------------------------


def compute_sync_plan(
    local: SyncManifest,
    remote: SyncManifest,
    last_synced: SyncManifest | None = None,
    *,
    local_data_dir: Path | None = None,
    remote_file_reader=None,
) -> list[SyncAction]:
    """Compute the list of sync actions via three-way merge.

    Parameters
    ----------
    local : SyncManifest
        Current local file state.
    remote : SyncManifest
        Current remote file state (fetched from daemon).
    last_synced : SyncManifest | None
        Snapshot from right after the previous sync completed.  If ``None``
        this is treated as a first-ever sync.
    local_data_dir : Path | None
        Local data directory, only needed for conflict resolution that
        requires reading file content.
    remote_file_reader : callable | None
        ``fn(rel_path) -> bytes`` for reading remote file content during
        conflict resolution.
    """
    actions: list[SyncAction] = []
    base = last_synced.entries if last_synced else {}
    all_paths = set(local.entries) | set(remote.entries) | set(base)

    for path in sorted(all_paths):
        l_entry = local.entries.get(path)
        r_entry = remote.entries.get(path)
        b_entry = base.get(path)

        l_hash = l_entry.content_hash if l_entry else None
        r_hash = r_entry.content_hash if r_entry else None
        b_hash = b_entry.content_hash if b_entry else None

        # Both exist and are identical → no-op
        if l_hash and r_hash and l_hash == r_hash:
            continue

        # ---- File exists only on one side (new or deleted) ----

        if l_entry and not r_entry:
            if b_entry:
                # Was in last_synced, now gone from remote → remote deleted
                actions.append(SyncAction(path, "pull", "deleted"))
            else:
                # New locally
                actions.append(SyncAction(path, "push", "new"))
            continue

        if r_entry and not l_entry:
            if b_entry:
                # Was in last_synced, now gone locally → local deleted
                actions.append(SyncAction(path, "push", "deleted"))
            else:
                # New remotely
                actions.append(SyncAction(path, "pull", "new"))
            continue

        # ---- Both exist, hashes differ ----

        l_changed = l_hash != b_hash
        r_changed = r_hash != b_hash

        if l_changed and not r_changed:
            actions.append(SyncAction(path, "push", "updated"))
        elif r_changed and not l_changed:
            actions.append(SyncAction(path, "pull", "updated"))
        elif l_changed and r_changed:
            # True conflict — resolve by file type
            local_bytes = None
            remote_bytes = None
            if local_data_dir:
                try:
                    local_bytes = (local_data_dir / path).read_bytes()
                except OSError:
                    pass
            if remote_file_reader:
                try:
                    remote_bytes = remote_file_reader(path)
                except Exception:
                    pass
            direction = _resolve_conflict(path, local_bytes, remote_bytes)
            actions.append(SyncAction(path, direction, "updated"))
        else:
            # Both changed from base but have different hashes, yet neither
            # changed from base? This means b_hash is None (first sync) and
            # both sides have the file with different content.
            # Treat as conflict with remote winning by default.
            direction = _resolve_conflict(path, None, None)
            actions.append(SyncAction(path, direction, "updated"))

    return actions
