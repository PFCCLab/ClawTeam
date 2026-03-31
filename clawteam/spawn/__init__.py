"""Spawn backends for launching team agents."""

from __future__ import annotations

from clawteam.spawn.base import SpawnBackend


def get_backend(name: str = "tmux", **kwargs) -> SpawnBackend:
    """Factory function to get a spawn backend by name."""
    if name == "http":
        from clawteam.spawn.http_backend import HTTPBackend
        return HTTPBackend(**kwargs)
    elif name == "subprocess":
        from clawteam.spawn.subprocess_backend import SubprocessBackend
        return SubprocessBackend()
    elif name == "tmux":
        from clawteam.spawn.tmux_backend import TmuxBackend
        return TmuxBackend()
    else:
        raise ValueError(f"Unknown spawn backend: {name}. Available: http, subprocess, tmux")


__all__ = ["SpawnBackend", "get_backend"]
