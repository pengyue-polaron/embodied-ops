"""Dependency-free transport endpoint validation."""

from __future__ import annotations

from pathlib import Path

from .errors import ContractError

UNIX_PREFIX = "unix://"


def unix_socket_path(endpoint: str) -> Path:
    if not isinstance(endpoint, str) or endpoint.strip() != endpoint:
        raise ContractError(f"invalid RPC endpoint: {endpoint!r}")
    if not endpoint.startswith("unix:///"):
        raise ContractError("RPC endpoint must use an absolute unix:/// path")
    path = Path(endpoint.removeprefix(UNIX_PREFIX))
    if not path.is_absolute() or str(path) == "/":
        raise ContractError("RPC Unix socket path must be absolute and non-root")
    if len(str(path).encode()) > 100:
        raise ContractError("RPC Unix socket path is too long for portable AF_UNIX use")
    return path
