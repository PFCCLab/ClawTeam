"""HTTP sync client and background sync loop.

:class:`SyncClient` talks to the daemon's ``/sync/*`` endpoints.
:class:`SyncLoop` runs a daemon thread that repeatedly calls
:meth:`sync_once` to keep a local ``data_dir`` in sync with the remote.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from clawteam.fileutil import atomic_write_text
from clawteam.sync.engine import SyncAction, compute_sync_plan
from clawteam.sync.manifest import (
    SyncManifest,
    _ScanCache,
    scan_manifest,
    validate_rel_path,
)
from clawteam.team.models import get_data_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SyncResult
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    """Outcome of a single sync round."""

    pushed: int = 0
    pulled: int = 0
    push_deletions: int = 0
    pull_deletions: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SyncClient — HTTP calls to the daemon
# ---------------------------------------------------------------------------


class SyncClient:
    """HTTP client for file sync with a remote daemon."""

    def __init__(
        self,
        remote_url: str,
        team_name: str,
        token: str = "",
        data_dir: Path | None = None,
        timeout: float = 30.0,
    ):
        self.remote_url = remote_url.rstrip("/")
        self.team_name = team_name
        self.token = token
        self.data_dir = data_dir or get_data_dir()
        self.timeout = timeout

    # -- helpers -------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request(self, method: str, path: str, body: bytes | None = None) -> bytes:
        url = f"{self.remote_url}{path}"
        req = urllib.request.Request(url, data=body, headers=self._headers(), method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    # -- sync endpoints ------------------------------------------------------

    def get_remote_manifest(self) -> SyncManifest:
        """``GET /sync/manifest?team={team}``"""
        raw = self._request("GET", f"/sync/manifest?team={self.team_name}")
        data = json.loads(raw)
        return SyncManifest.from_dict(data)

    def pull_files(self, paths: list[str]) -> dict[str, bytes]:
        """``POST /sync/pull`` — batch fetch file contents (base64-encoded)."""
        body = json.dumps({"team": self.team_name, "paths": paths}).encode()
        raw = self._request("POST", "/sync/pull", body)
        data = json.loads(raw)
        result: dict[str, bytes] = {}
        for rel, b64 in data.get("files", {}).items():
            result[rel] = base64.b64decode(b64)
        return result

    def push_files(
        self,
        files: dict[str, bytes],
        deletions: list[str] | None = None,
    ) -> dict:
        """``POST /sync/push`` — batch upload file contents (base64-encoded)."""
        encoded = {rel: base64.b64encode(content).decode() for rel, content in files.items()}
        body = json.dumps({
            "team": self.team_name,
            "files": encoded,
            "deletions": deletions or [],
        }).encode()
        raw = self._request("POST", "/sync/push", body)
        return json.loads(raw)


# ---------------------------------------------------------------------------
# SyncLoop — background daemon thread
# ---------------------------------------------------------------------------


class SyncLoop:
    """Background sync loop that keeps local and remote data_dir in sync."""

    def __init__(
        self,
        client: SyncClient,
        team_name: str,
        poll_interval: float = 5.0,
        data_dir: Path | None = None,
    ):
        self.client = client
        self.team_name = team_name
        self.poll_interval = poll_interval
        self.data_dir = data_dir or get_data_dir()
        self._last_synced: SyncManifest | None = None
        self._stop = threading.Event()
        self._scan_cache = _ScanCache()
        self._thread: threading.Thread | None = None

    def sync_once(self) -> SyncResult:
        """Execute one complete sync round: scan → diff → push/pull."""
        result = SyncResult()

        # 1. Scan local
        local = scan_manifest(self.team_name, self.data_dir, self._scan_cache)

        # 2. Fetch remote manifest
        try:
            remote = self.client.get_remote_manifest()
        except Exception as exc:
            result.errors.append(f"Failed to fetch remote manifest: {exc}")
            return result

        # 3. Compute sync plan
        def _remote_reader(rel_path: str) -> bytes:
            files = self.client.pull_files([rel_path])
            return files.get(rel_path, b"")

        actions = compute_sync_plan(
            local,
            remote,
            self._last_synced,
            local_data_dir=self.data_dir,
            remote_file_reader=_remote_reader,
        )

        if not actions:
            self._last_synced = _merged_snapshot(local, remote)
            return result

        # 4. Partition actions
        pull_paths = [a.rel_path for a in actions if a.direction == "pull" and a.reason != "deleted"]
        push_paths = [a.rel_path for a in actions if a.direction == "push" and a.reason != "deleted"]
        pull_deletions = [a.rel_path for a in actions if a.direction == "pull" and a.reason == "deleted"]
        push_deletions = [a.rel_path for a in actions if a.direction == "push" and a.reason == "deleted"]

        # 5. Pull files from remote → write locally
        if pull_paths:
            try:
                pulled = self.client.pull_files(pull_paths)
                for rel, content in pulled.items():
                    target = self.data_dir / rel
                    atomic_write_text(target, content.decode("utf-8", errors="replace"))
                result.pulled = len(pulled)
            except Exception as exc:
                result.errors.append(f"Pull failed: {exc}")

        # 6. Handle pull deletions (remote deleted → delete locally)
        for rel in pull_deletions:
            target = self.data_dir / rel
            try:
                target.unlink(missing_ok=True)
                result.pull_deletions += 1
            except OSError:
                pass

        # 7. Push files to remote
        if push_paths:
            files_to_push: dict[str, bytes] = {}
            for rel in push_paths:
                src = self.data_dir / rel
                try:
                    files_to_push[rel] = src.read_bytes()
                except OSError as exc:
                    result.errors.append(f"Cannot read {rel}: {exc}")
            if files_to_push:
                try:
                    resp = self.client.push_files(files_to_push, deletions=push_deletions)
                    result.pushed = resp.get("written", len(files_to_push))
                    result.push_deletions = resp.get("deleted", len(push_deletions))
                    for path, err in resp.get("errors", {}).items():
                        result.errors.append(f"Push error {path}: {err}")
                except Exception as exc:
                    result.errors.append(f"Push failed: {exc}")
        elif push_deletions:
            try:
                resp = self.client.push_files({}, deletions=push_deletions)
                result.push_deletions = resp.get("deleted", len(push_deletions))
            except Exception as exc:
                result.errors.append(f"Push deletions failed: {exc}")

        # 8. Update last_synced snapshot
        # Re-scan local after writes to get accurate hashes
        local_after = scan_manifest(self.team_name, self.data_dir, self._scan_cache)
        try:
            remote_after = self.client.get_remote_manifest()
        except Exception:
            remote_after = remote
        self._last_synced = _merged_snapshot(local_after, remote_after)

        return result

    def start_background(self) -> threading.Thread:
        """Start the sync loop in a daemon thread."""
        t = threading.Thread(target=self._run, daemon=True, name=f"sync-{self.team_name}")
        t.start()
        self._thread = t
        return t

    def stop(self) -> None:
        """Signal the sync loop to stop."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.poll_interval + 2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.sync_once()
                if result.errors:
                    for err in result.errors:
                        logger.warning("sync: %s", err)
                elif result.pushed or result.pulled:
                    logger.debug(
                        "sync: pushed=%d pulled=%d", result.pushed, result.pulled
                    )
            except Exception:
                logger.exception("sync: unexpected error")
            self._stop.wait(self.poll_interval)


def _merged_snapshot(local: SyncManifest, remote: SyncManifest) -> SyncManifest:
    """Build a combined snapshot from both sides (union of entries)."""
    merged = dict(local.entries)
    for k, v in remote.entries.items():
        if k not in merged:
            merged[k] = v
    return SyncManifest(entries=merged, scanned_at_ns=max(local.scanned_at_ns, remote.scanned_at_ns))
