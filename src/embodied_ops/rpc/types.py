"""Transport-owned value and session types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from embodied_ops.errors import ContractError

PROTOCOL_VERSION = 1


class SessionMode(str, Enum):
    """Access requested by one remote session."""

    OBSERVE = "observe"
    COMMAND = "command"


@dataclass(frozen=True, slots=True)
class TensorValue:
    """Dependency-free row-major tensor payload used by the RPC boundary."""

    dtype: str
    shape: tuple[int, ...]
    data: bytes

    def __post_init__(self) -> None:
        if not self.dtype:
            raise ContractError("tensor dtype must not be empty")
        if any(
            not isinstance(size, int) or isinstance(size, bool) or size <= 0 for size in self.shape
        ):
            raise ContractError(f"invalid tensor shape: {self.shape!r}")
        if not isinstance(self.data, bytes):
            raise ContractError("tensor data must be bytes")
