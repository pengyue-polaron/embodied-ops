"""Exclusive subprocess ownership for a local operator panel."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import InputAction, WorkflowLaunch
from .protocol import (
    PROTOCOL_ENV,
    InputEvent,
    InvalidEvent,
    ProgressEvent,
    parse_event,
)


class WorkflowProcess:
    def __init__(self, repo_root: Path, *, max_log_lines: int = 500) -> None:
        self.repo_root = repo_root.resolve()
        self.max_log_lines = max_log_lines
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._workflow = ""
        self._name = ""
        self._command: tuple[str, ...] = ()
        self._started_at = ""
        self._exit_code: int | None = None
        self._logs: deque[str] = deque(maxlen=max_log_lines)
        self._status_line = ""
        self._progress: dict[str, ProgressEvent] = {}
        self._input_actions: dict[str, InputAction] = {}
        self._available_input: tuple[str, ...] = ()

    def start(self, launch: WorkflowLaunch) -> dict[str, Any]:
        with self._lock:
            if self._is_active_locked():
                raise RuntimeError(f"workflow already active: {self._name}")
            action_ids = [action.action_id for action in launch.input_actions]
            if len(set(action_ids)) != len(action_ids):
                raise ValueError("workflow input action ids must be unique")
            invalid_tones = [
                action.tone
                for action in launch.input_actions
                if action.tone not in {"default", "primary", "danger", "quiet"}
            ]
            if invalid_tones:
                raise ValueError(f"unsupported input action tone: {invalid_tones[0]!r}")
            environment = os.environ.copy()
            environment.update(
                {
                    "NO_COLOR": "1",
                    "PYTHONUNBUFFERED": "1",
                    PROTOCOL_ENV: "1",
                }
            )
            process = subprocess.Popen(
                launch.command,
                cwd=self.repo_root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            self._process = process
            self._workflow = launch.workflow
            self._name = launch.name
            self._command = launch.command
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._exit_code = None
            self._logs.clear()
            self._logs.append(f"[PANEL] started {launch.name}")
            self._logs.append(f"[PANEL] command {shlex.join(launch.command)}")
            self._status_line = ""
            self._progress.clear()
            self._input_actions = {action.action_id: action for action in launch.input_actions}
            self._available_input = ()
            thread = threading.Thread(
                target=self._read_output,
                args=(process,),
                name="operator-panel-workflow-output",
                daemon=True,
            )
            thread.start()
            return self._snapshot_locked()

    def send(self, action_id: str) -> dict[str, Any]:
        with self._lock:
            if not self._is_active_locked() or self._process is None:
                raise RuntimeError("no active workflow")
            if action_id not in self._available_input:
                raise RuntimeError(f"workflow is not waiting for input action: {action_id!r}")
            action = self._input_actions[action_id]
            if self._process.stdin is None:
                raise RuntimeError("active workflow has no input channel")
            previous = self._available_input
            self._available_input = ()
            try:
                self._process.stdin.write(action.line)
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._available_input = previous
                raise RuntimeError("active workflow closed its input channel") from exc
            self._logs.append(f"[PANEL] input {action_id}")
            return self._snapshot_locked()

    def stop(self, *, timeout_s: float = 12.0) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return self._snapshot_locked()
            self._logs.append("[PANEL] interrupt requested")
            self._available_input = ()
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            with self._lock:
                return self._snapshot_locked()
        try:
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "workflow did not stop after SIGINT; run the repository cleanup "
                "command before retrying"
            ) from exc
        with self._lock:
            self._exit_code = process.returncode
            return self._snapshot_locked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def _read_output(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            event = parse_event(line)
            with self._lock:
                if self._process is not process:
                    continue
                if isinstance(event, InputEvent):
                    self._available_input = tuple(
                        action_id for action_id in event.actions if action_id in self._input_actions
                    )
                    continue
                if isinstance(event, ProgressEvent):
                    self._progress[event.progress_id] = event
                    continue
                if isinstance(event, InvalidEvent):
                    self._logs.append(
                        f"[WARN] Ignored invalid operator-panel event: {event.reason}"
                    )
                    continue
                if line.startswith("[RUN] "):
                    self._status_line = line
                    continue
                if self._status_line and not line.strip():
                    self._status_line = ""
                    continue
                self._status_line = ""
                self._logs.append(line)
        return_code = process.wait()
        with self._lock:
            if self._process is process:
                self._exit_code = return_code
                self._available_input = ()
                self._status_line = ""
                self._logs.append(f"[PANEL] exited {return_code}")

    def _is_active_locked(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _snapshot_locked(self) -> dict[str, Any]:
        active = self._is_active_locked()
        if self._process is not None and not active:
            self._exit_code = self._process.returncode
            self._available_input = ()
        return {
            "active": active,
            "workflow": self._workflow,
            "name": self._name,
            "command": list(self._command),
            "started_at": self._started_at,
            "exit_code": self._exit_code,
            "progress": [
                self._progress[progress_id].as_json() for progress_id in sorted(self._progress)
            ],
            "status_line": self._status_line,
            "input_actions": [
                {
                    "id": action_id,
                    "label": self._input_actions[action_id].label,
                    "tone": self._input_actions[action_id].tone,
                }
                for action_id in self._available_input
            ],
            "logs": list(self._logs),
        }
