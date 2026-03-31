"""HTTP spawn backend — delegates agent creation to a remote daemon."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from clawteam.spawn.base import SpawnBackend
from clawteam.spawn.registry import register_agent
from clawteam.sync.client import SyncClient, SyncLoop
from clawteam.team.models import get_data_dir

logger = logging.getLogger(__name__)


class HTTPBackend(SpawnBackend):
    """Spawn backend that talks to a remote daemon over HTTP.

    After a successful spawn the backend automatically starts a
    :class:`~clawteam.sync.client.SyncLoop` daemon thread to keep the
    local ``data_dir`` synchronised with the remote.
    """

    def __init__(
        self,
        node_url: str,
        token: str = "",
        team_name: str = "",
        sync_interval: float = 5.0,
    ):
        self.node_url = node_url.rstrip("/")
        self.token = token
        self.team_name = team_name
        self.sync_interval = sync_interval
        self.workspace: bool = True  # request daemon to create worktree by default
        self._sync_loops: dict[str, SyncLoop] = {}

    # -- SpawnBackend interface ----------------------------------------------

    def spawn(
        self,
        command: list[str],
        agent_name: str,
        agent_id: str,
        agent_type: str,
        team_name: str,
        prompt: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        skip_permissions: bool = False,
        system_prompt: str | None = None,
    ) -> str:
        payload = {
            "command": command,
            "agent_name": agent_name,
            "agent_id": agent_id,
            "agent_type": agent_type,
            "team_name": team_name,
            "prompt": prompt,
            "env": env,
            "cwd": cwd,
            "skip_permissions": skip_permissions,
            "system_prompt": system_prompt,
            "workspace": self.workspace,
        }

        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        url = f"{self.node_url}/spawn"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode(errors="replace")
            return f"Error: HTTP {exc.code} from daemon: {err_body}"
        except Exception as exc:
            return f"Error: cannot reach daemon at {self.node_url}: {exc}"

        if data.get("status") != "spawned":
            return f"Error: daemon returned unexpected status: {data}"

        # Write peer_info locally so P2P transport can connect
        peer_info = data.get("peer_info", {})
        if peer_info:
            peers_dir = get_data_dir() / "teams" / team_name / "peers"
            peers_dir.mkdir(parents=True, exist_ok=True)
            peer_path = peers_dir / f"{agent_name}.json"
            peer_path.write_text(json.dumps(peer_info, indent=2))

        # Register in local spawn registry
        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="http",
            node_url=self.node_url,
        )

        # Start background sync loop
        self._start_sync(team_name)

        message = data.get("message", f"Agent '{agent_name}' spawned on {self.node_url}")
        return message

    def list_running(self) -> list[dict[str, str]]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        team = self.team_name or "default"
        url = f"{self.node_url}/agents?team={team}"
        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            agents = data.get("agents", [])
            return [
                {"name": a["name"], "backend": a.get("backend", "http")}
                for a in agents
                if a.get("alive") is True
            ]
        except Exception as exc:
            logger.warning("list_running from %s failed: %s", self.node_url, exc)
            return []

    # -- sync management -----------------------------------------------------

    def _start_sync(self, team_name: str) -> None:
        if team_name in self._sync_loops:
            return
        client = SyncClient(
            remote_url=self.node_url,
            team_name=team_name,
            token=self.token,
        )
        loop = SyncLoop(
            client=client,
            team_name=team_name,
            poll_interval=self.sync_interval,
        )
        loop.start_background()
        self._sync_loops[team_name] = loop
        logger.info("Started sync loop for team '%s' with %s", team_name, self.node_url)

    def stop_sync(self, team_name: str = "") -> None:
        """Stop sync loops (all or for a specific team)."""
        if team_name:
            loop = self._sync_loops.pop(team_name, None)
            if loop:
                loop.stop()
        else:
            for loop in self._sync_loops.values():
                loop.stop()
            self._sync_loops.clear()
