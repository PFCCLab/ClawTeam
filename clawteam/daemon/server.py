"""HTTP Daemon server for remote agent spawning and file sync.

Follows the same ``ThreadingHTTPServer`` + ``BaseHTTPRequestHandler`` pattern
used by :mod:`clawteam.board.server`.
"""

from __future__ import annotations

import base64
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from clawteam.daemon.auth import check_auth
from clawteam.fileutil import atomic_write_text
from clawteam.sync.manifest import (
    SyncManifest,
    is_syncable_path,
    scan_manifest,
    validate_rel_path,
)
from clawteam.team.models import get_data_dir

logger = logging.getLogger(__name__)


class DaemonHandler(BaseHTTPRequestHandler):
    """HTTP handler for spawn management and file sync endpoints."""

    # Set before serving via class attributes (same pattern as BoardHandler)
    token: str = ""
    default_backend: str = "tmux"
    data_dir: Path = Path()
    repo_root: str = ""            # git repo path; empty means no worktree creation
    _workspace_agents: dict = {}   # {"team/agent": True} tracks agents with worktrees

    # -- routing -------------------------------------------------------------

    def do_GET(self):
        try:
            self._route_get()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_POST(self):
        try:
            self._route_post()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _route_get(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/healthz":
            self._json_ok({"status": "ok"})
            return

        # All other GETs require auth
        if not self._check_auth():
            return

        if path.startswith("/status/"):
            agent = path[len("/status/"):]
            team = qs.get("team", [""])[0]
            self._handle_status(agent, team)
        elif path == "/agents":
            team = qs.get("team", [""])[0]
            self._handle_list_agents(team)
        elif path == "/sync/manifest":
            team = qs.get("team", [""])[0]
            self._handle_sync_manifest(team)
        else:
            self.send_error(404)

    def _route_post(self):
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/spawn":
            self._handle_spawn()
        elif path.startswith("/stop/"):
            agent = path[len("/stop/"):]
            team = qs.get("team", [""])[0]
            self._handle_stop(agent, team)
        elif path == "/sync/pull":
            self._handle_sync_pull()
        elif path == "/sync/push":
            self._handle_sync_push()
        else:
            self.send_error(404)

    # -- auth ----------------------------------------------------------------

    def _check_auth(self) -> bool:
        if not check_auth(self.headers, self.token):
            self.send_error(401, "Unauthorized")
            return False
        return True

    # -- spawn endpoints -----------------------------------------------------

    def _handle_spawn(self):
        body = self._read_json()
        if body is None:
            return

        command = body.get("command", ["claude"])
        agent_name = body.get("agent_name", "")
        agent_id = body.get("agent_id", "")
        agent_type = body.get("agent_type", "general-purpose")
        team_name = body.get("team_name", "")
        prompt = body.get("prompt")
        env = body.get("env")
        cwd = body.get("cwd")
        skip_permissions = body.get("skip_permissions", True)
        system_prompt = body.get("system_prompt")
        backend = body.get("backend", self.default_backend)

        if not agent_name or not team_name:
            self._json_error(400, "agent_name and team_name are required")
            return

        workspace = body.get("workspace", False)

        # Create worktree if requested and repo_root is configured
        ws_cwd = None
        ws_created = False
        ws_mgr = None
        if workspace and self.repo_root:
            try:
                from clawteam.workspace import get_workspace_manager
                ws_mgr = get_workspace_manager(self.repo_root)
                if ws_mgr is not None:
                    ws_info = ws_mgr.create_workspace(team_name, agent_name, agent_id)
                    ws_cwd = ws_info.worktree_path
                    ws_created = True
            except Exception as exc:
                logger.warning("Worktree creation failed for %s/%s: %s", team_name, agent_name, exc)

        try:
            from clawteam.spawn import get_backend
            be = get_backend(backend)
            result = be.spawn(
                command=command,
                agent_name=agent_name,
                agent_id=agent_id,
                agent_type=agent_type,
                team_name=team_name,
                prompt=prompt,
                env=env,
                cwd=ws_cwd or cwd,
                skip_permissions=skip_permissions,
                system_prompt=system_prompt,
            )
        except Exception as exc:
            # Clean up worktree on spawn failure
            if ws_created and ws_mgr is not None:
                try:
                    ws_mgr.cleanup_workspace(team_name, agent_name, auto_checkpoint=False)
                except Exception:
                    pass
            self._json_error(500, f"Spawn failed: {exc}")
            return

        if ws_created:
            DaemonHandler._workspace_agents[f"{team_name}/{agent_name}"] = True

        # Collect peer_info if available
        peer_info = self._read_peer_info(team_name, agent_name)

        self._json_ok({
            "status": "spawned",
            "message": result,
            "agent_name": agent_name,
            "peer_info": peer_info,
            "worktree": ws_cwd,
        })

    def _handle_status(self, agent_name: str, team_name: str):
        if not agent_name or not team_name:
            self._json_error(400, "agent name and team query param required")
            return
        import concurrent.futures
        from clawteam.spawn.registry import is_agent_alive
        # Run liveness check with timeout to prevent tmux hangs from blocking the server
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            try:
                future = pool.submit(is_agent_alive, team_name, agent_name)
                alive = future.result(timeout=5)
            except concurrent.futures.TimeoutError:
                alive = None
        self._json_ok({"agent": agent_name, "alive": alive})

    def _handle_stop(self, agent_name: str, team_name: str):
        if not agent_name or not team_name:
            self._json_error(400, "agent name and team query param required")
            return
        import concurrent.futures
        from clawteam.spawn.registry import stop_agent
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            try:
                future = pool.submit(stop_agent, team_name, agent_name)
                stopped = future.result(timeout=10)
            except concurrent.futures.TimeoutError:
                stopped = None

        # Clean up worktree if one was created for this agent
        key = f"{team_name}/{agent_name}"
        ws_cleaned = False
        if DaemonHandler._workspace_agents.pop(key, False) and self.repo_root:
            try:
                from clawteam.workspace import get_workspace_manager
                ws_mgr = get_workspace_manager(self.repo_root)
                if ws_mgr is not None:
                    ws_cleaned = ws_mgr.cleanup_workspace(team_name, agent_name)
            except Exception as exc:
                logger.warning("Worktree cleanup failed: %s", exc)

        self._json_ok({"agent": agent_name, "stopped": stopped, "worktree_cleaned": ws_cleaned})

    def _handle_list_agents(self, team_name: str):
        if not team_name:
            self._json_error(400, "team query param required")
            return
        from clawteam.spawn.registry import get_registry, is_agent_alive
        registry = get_registry(team_name)
        agents = []
        for name, info in registry.items():
            alive = is_agent_alive(team_name, name)
            agents.append({
                "name": name,
                "backend": info.get("backend", ""),
                "alive": alive,
                "pid": info.get("pid", 0),
                "spawned_at": info.get("spawned_at", 0),
            })
        self._json_ok({"team": team_name, "agents": agents})

    # -- sync endpoints ------------------------------------------------------

    def _handle_sync_manifest(self, team_name: str):
        if not team_name:
            self._json_error(400, "team query param required")
            return
        manifest = scan_manifest(team_name, self.data_dir)
        self._json_ok(manifest.to_dict())

    def _handle_sync_pull(self):
        body = self._read_json()
        if body is None:
            return
        team = body.get("team", "")
        paths = body.get("paths", [])
        if not team:
            self._json_error(400, "team is required")
            return

        files: dict[str, str] = {}
        for rel in paths:
            try:
                rel = validate_rel_path(rel)
            except ValueError:
                continue
            if not is_syncable_path(rel, team):
                continue
            abs_path = self.data_dir / rel
            if abs_path.is_file():
                try:
                    files[rel] = base64.b64encode(abs_path.read_bytes()).decode()
                except OSError:
                    pass

        self._json_ok({"files": files})

    def _handle_sync_push(self):
        body = self._read_json()
        if body is None:
            return
        team = body.get("team", "")
        files = body.get("files", {})
        deletions = body.get("deletions", [])
        if not team:
            self._json_error(400, "team is required")
            return

        written = 0
        deleted = 0
        errors: dict[str, str] = {}

        for rel, b64_content in files.items():
            try:
                rel = validate_rel_path(rel)
            except ValueError as exc:
                errors[rel] = str(exc)
                continue
            if not is_syncable_path(rel, team):
                errors[rel] = "path not in sync scope"
                continue
            try:
                content = base64.b64decode(b64_content)
                target = self.data_dir / rel
                atomic_write_text(target, content.decode("utf-8", errors="replace"))
                written += 1
            except Exception as exc:
                errors[rel] = str(exc)

        for rel in deletions:
            try:
                rel = validate_rel_path(rel)
            except ValueError:
                continue
            if not is_syncable_path(rel, team):
                continue
            target = self.data_dir / rel
            try:
                target.unlink(missing_ok=True)
                deleted += 1
            except OSError:
                pass

        self._json_ok({"ok": True, "written": written, "deleted": deleted, "errors": errors})

    # -- helpers -------------------------------------------------------------

    def _read_json(self) -> dict | None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._json_error(400, "Empty body")
            return None
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            self._json_error(400, f"Invalid JSON: {exc}")
            return None

    def _json_ok(self, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, code: int, message: str):
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_peer_info(self, team_name: str, agent_name: str) -> dict:
        peer_path = get_data_dir() / "teams" / team_name / "peers" / f"{agent_name}.json"
        if peer_path.exists():
            try:
                return json.loads(peer_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def log_message(self, format, *args):
        # Suppress noisy /status/ polling logs
        first = str(args[0]) if args else ""
        if "/status/" in first:
            return
        logger.info(format, *args)


# ---------------------------------------------------------------------------
# Public serve function
# ---------------------------------------------------------------------------


def serve(
    host: str = "0.0.0.0",
    port: int = 9090,
    token: str = "",
    default_backend: str = "tmux",
    data_dir: Path | None = None,
    repo_root: str = "",
) -> None:
    """Start the daemon HTTP server.

    This is the entry point called by ``clawteam daemon start``.
    """
    if data_dir is None:
        data_dir = get_data_dir()

    DaemonHandler.token = token
    DaemonHandler.default_backend = default_backend
    DaemonHandler.data_dir = data_dir
    DaemonHandler.repo_root = repo_root
    DaemonHandler._workspace_agents = {}

    server = ThreadingHTTPServer((host, port), DaemonHandler)
    logger.info("Daemon listening on %s:%d", host, port)
    print(f"ClawTeam daemon listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
