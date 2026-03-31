"""Named node alias management."""

from __future__ import annotations

from clawteam.config import NodeConfig, load_config, save_config


def resolve_node(value: str | None) -> tuple[str, str]:
    """Resolve a --node value to (url, token).

    If value looks like a URL (contains '://'), use it directly.
    Otherwise, treat it as a named alias and look up in config.nodes.
    Returns (url, token). Raises ValueError if alias not found.
    """
    if not value:
        return "", ""
    if "://" in value:
        return value, ""
    cfg = load_config()
    node = cfg.nodes.get(value)
    if node is None:
        available = ", ".join(sorted(cfg.nodes.keys())) or "(none)"
        raise ValueError(
            f"Unknown node '{value}'. Available nodes: {available}. "
            f"Use a full URL or configure with: clawteam node set {value} --url <url>"
        )
    return node.url, node.token


def load_node(name: str) -> NodeConfig:
    """Load a named node from config or raise ValueError."""
    cfg = load_config()
    if name not in cfg.nodes:
        raise ValueError(f"Node '{name}' not found")
    return cfg.nodes[name]


def save_node(name: str, node: NodeConfig) -> None:
    """Persist a named node."""
    cfg = load_config()
    cfg.nodes[name] = node
    save_config(cfg)


def remove_node(name: str) -> None:
    """Remove a node. Raises ValueError if not found."""
    cfg = load_config()
    if name not in cfg.nodes:
        raise ValueError(f"Node '{name}' not found")
    del cfg.nodes[name]
    save_config(cfg)


def list_nodes() -> dict[str, NodeConfig]:
    """Return all configured nodes."""
    return load_config().nodes
