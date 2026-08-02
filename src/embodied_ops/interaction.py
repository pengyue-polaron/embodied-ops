"""Shared operator actions used by terminal and Web workflow surfaces."""

from __future__ import annotations

import re
from dataclasses import dataclass


_ACTION_ID = re.compile(r"[a-z][a-z0-9_-]*")
_ACTION_TONES = {"default", "primary", "danger", "quiet"}


@dataclass(frozen=True, slots=True)
class InputAction:
    action_id: str
    label: str
    line: str
    tone: str = "default"

    def __post_init__(self) -> None:
        if _ACTION_ID.fullmatch(self.action_id) is None:
            raise ValueError("input action id must be a lowercase identifier")
        if not self.label or self.label != self.label.strip():
            raise ValueError("input action label must be non-empty without surrounding space")
        if not self.line or "\x00" in self.line:
            raise ValueError("input action line must be non-empty and contain no NUL byte")
        if self.tone not in _ACTION_TONES:
            raise ValueError(f"unsupported input action tone: {self.tone!r}")
