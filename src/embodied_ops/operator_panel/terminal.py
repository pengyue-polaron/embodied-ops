"""TTY input bound to the currently displayed, one-shot workflow gate."""

from __future__ import annotations

import os
import select
import sys
import termios
from typing import Any, TextIO

from embodied_ops.interaction import InputAction


class WorkflowTerminal:
    """Read only interactive terminals; never queue input across gate changes."""

    def __init__(self, actions: tuple[InputAction, ...], stream: TextIO | None = None):
        self._stream = sys.stdin if stream is None else stream
        self._fd = self._stream.fileno() if self._stream.isatty() else None
        self._actions = {action.action_id: action for action in actions}
        self._gate: tuple[str, int] | None = None
        self._consumed = False

    def poll(self, status: dict[str, Any], timeout: float) -> str | None:
        if self._fd is None:
            select.select([], [], [], timeout)
            return None
        gate = (status["run_id"], status["input_revision"])
        available = tuple(
            self._actions[item["id"]]
            for item in status.get("input_actions", [])
            if item["id"] in self._actions
        )
        if gate != self._gate:
            # Discard complete AND partially typed input from the previous phase.
            termios.tcflush(self._fd, termios.TCIFLUSH)
            self._gate = gate
            self._consumed = False
            if available:
                choices = " | ".join(
                    f"{action.line.strip() + '+Enter' if action.line.strip() else 'Enter'}"
                    f"={action.label}"
                    for action in available
                )
                print(f"[INPUT] {status.get('input_detail', '')}\n{choices}", flush=True)
        if not select.select([self._fd], [], [], timeout)[0]:
            return None
        data = os.read(self._fd, 4096)
        if not data:
            self._fd = None
            print("[INFO] Terminal input closed; external controls remain available.", flush=True)
            return None
        # One batch can authorize at most one action, even for pasted lines.
        termios.tcflush(self._fd, termios.TCIFLUSH)
        if not available or self._consumed:
            return None
        if b"\n" not in data:
            print("[WARN] Incomplete terminal input ignored.", flush=True)
            return None
        line = data.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip().lower()
        matching = [action for action in available if action.line.strip() == line]
        if len(matching) != 1:
            print("[WARN] Input unavailable; use a key shown above.", flush=True)
            return None
        self._consumed = True
        return matching[0].action_id
