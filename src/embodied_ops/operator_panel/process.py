"""Exclusive subprocess ownership for a local operator panel."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import InputAction, WorkflowLaunch
from .owned_process import owned_command
from .protocol import (
    PANEL_EVENT_SCHEMA_VERSION,
    PROTOCOL_ENV,
    PROTOCOL_VERSION_ENV,
    InputEvent,
    InvalidEvent,
    ProgressEvent,
    parse_event,
)


WORKFLOW_STATUS_SCHEMA_VERSION = 2


class WorkflowProcess:
    def __init__(self, repo_root: Path, *, max_log_lines: int = 500) -> None:
        self.repo_root = repo_root.resolve()
        self.max_log_lines = max_log_lines
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._workflow = ""
        self._name = ""
        self._command: tuple[str, ...] = ()
        self._run_id = ""
        self._revision = 0
        self._started_at = ""
        self._finished_at = ""
        self._exit_code: int | None = None
        self._stop_requested = False
        self._logs: deque[str] = deque(maxlen=max_log_lines)
        self._status_line = ""
        self._progress: dict[str, ProgressEvent] = {}
        self._input_actions: dict[str, InputAction] = {}
        self._available_input: tuple[str, ...] = ()
        self._input_revision = 0
        self._input_phase = ""
        self._input_detail = ""

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
                    PROTOCOL_VERSION_ENV: str(PANEL_EVENT_SCHEMA_VERSION),
                }
            )
            supervised_command, owner_environment = owned_command(
                launch.command,
                owner_pid=os.getpid(),
            )
            environment.update(owner_environment)
            process = subprocess.Popen(
                supervised_command,
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
            self._run_id = str(uuid.uuid4())
            self._revision = 1
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._finished_at = ""
            self._exit_code = None
            self._stop_requested = False
            self._logs.clear()
            self._logs.append(f"[PANEL] started {launch.name}")
            self._logs.append(f"[PANEL] command {shlex.join(launch.command)}")
            self._status_line = ""
            self._progress.clear()
            self._input_actions = {action.action_id: action for action in launch.input_actions}
            self._available_input = ()
            self._input_revision = 0
            self._input_phase = ""
            self._input_detail = ""
            thread = threading.Thread(
                target=self._read_output,
                args=(process,),
                name="operator-panel-workflow-output",
                daemon=True,
            )
            thread.start()
            return self._snapshot_locked()

    def send(
        self,
        action_id: str,
        *,
        run_id: str,
        input_revision: int,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._is_active_locked() or self._process is None:
                raise RuntimeError("no active workflow")
            if run_id != self._run_id:
                raise RuntimeError("workflow run changed before input was accepted")
            if (
                isinstance(input_revision, bool)
                or not isinstance(input_revision, int)
                or input_revision != self._input_revision
            ):
                raise RuntimeError("workflow input gate changed before input was accepted")
            if action_id not in self._available_input:
                raise RuntimeError(f"workflow is not waiting for input action: {action_id!r}")
            action = self._input_actions[action_id]
            if self._process.stdin is None:
                raise RuntimeError("active workflow has no input channel")
            previous = self._available_input
            previous_phase = self._input_phase
            previous_detail = self._input_detail
            self._available_input = ()
            self._input_phase = ""
            self._input_detail = ""
            self._input_revision += 1
            try:
                self._process.stdin.write(action.line)
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._available_input = previous
                self._input_phase = previous_phase
                self._input_detail = previous_detail
                self._input_revision -= 1
                raise RuntimeError("active workflow closed its input channel") from exc
            self._logs.append(f"[PANEL] input {action_id}")
            self._revision += 1
            return self._snapshot_locked()

    def stop(
        self,
        *,
        run_id: str | None = None,
        timeout_s: float = 12.0,
    ) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return self._snapshot_locked()
            if run_id is not None and run_id != self._run_id:
                raise RuntimeError("workflow run changed before stop was accepted")
            self._logs.append("[PANEL] interrupt requested")
            self._available_input = ()
            self._input_phase = ""
            self._input_detail = ""
            self._input_revision += 1
            self._stop_requested = True
            self._revision += 1
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
            self._finalize_locked(process.returncode)
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
                    unknown = tuple(
                        action_id
                        for action_id in event.actions
                        if action_id not in self._input_actions
                    )
                    self._available_input = tuple(
                        action_id for action_id in event.actions if action_id in self._input_actions
                    )
                    self._input_phase = event.phase
                    self._input_detail = event.detail
                    self._input_revision += 1
                    if unknown:
                        self._logs.append(
                            "[WARN] Ignored undeclared operator-panel input actions: "
                            + ", ".join(unknown)
                        )
                    self._revision += 1
                    continue
                if isinstance(event, ProgressEvent):
                    self._progress[event.progress_id] = event
                    self._revision += 1
                    continue
                if isinstance(event, InvalidEvent):
                    self._logs.append(
                        f"[WARN] Ignored invalid operator-panel event: {event.reason}"
                    )
                    self._revision += 1
                    continue
                if line.startswith("[RUN] "):
                    self._status_line = line
                    self._revision += 1
                    continue
                if self._status_line and not line.strip():
                    self._status_line = ""
                    self._revision += 1
                    continue
                self._status_line = ""
                self._logs.append(line)
                self._revision += 1
        return_code = process.wait()
        with self._lock:
            if self._process is process:
                self._finalize_locked(return_code)

    def _is_active_locked(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _snapshot_locked(self) -> dict[str, Any]:
        active = self._is_active_locked()
        if self._process is not None and not active:
            self._finalize_locked(self._process.returncode)
        state = self._state_locked(active)
        return {
            "schema_version": WORKFLOW_STATUS_SCHEMA_VERSION,
            "revision": self._revision,
            "run_id": self._run_id,
            "state": state,
            "active": active,
            "workflow": self._workflow,
            "name": self._name,
            "command": list(self._command),
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "exit_code": self._exit_code,
            "progress": [
                self._progress[progress_id].as_json() for progress_id in sorted(self._progress)
            ],
            "status_line": self._status_line,
            "input_revision": self._input_revision,
            "input_phase": self._input_phase,
            "input_detail": self._input_detail,
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

    def _finalize_locked(self, return_code: int | None) -> None:
        if self._exit_code is not None or return_code is None:
            return
        self._exit_code = return_code
        self._finished_at = datetime.now(timezone.utc).isoformat()
        self._available_input = ()
        self._input_phase = ""
        self._input_detail = ""
        self._input_revision += 1
        self._status_line = ""
        self._logs.append(f"[PANEL] exited {return_code}")
        self._revision += 1

    def _state_locked(self, active: bool) -> str:
        if self._process is None:
            return "idle"
        if active:
            if self._stop_requested:
                return "stopping"
            if self._available_input:
                return "waiting_for_input"
            return "running"
        if self._stop_requested:
            return "stopped"
        if self._exit_code == 0:
            return "succeeded"
        return "failed"
