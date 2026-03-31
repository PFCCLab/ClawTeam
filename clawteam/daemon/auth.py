"""Bearer token authentication for the daemon HTTP server."""

from __future__ import annotations

import hmac


def check_auth(headers, expected_token: str) -> bool:
    """Validate a Bearer token from HTTP headers.

    Returns True if the token matches, or if *expected_token* is empty (auth
    disabled).
    """
    if not expected_token:
        return True
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    return hmac.compare_digest(auth[7:], expected_token)
