"""Source-neutral detached lifecycle for one composed teleoperation session."""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import zmq

from .foxglove_probe import is_foxglove_server_ready
from .zmq_transport import TeleopFeedbackReceiver

STATE_SCHEMA = "embodied.teleop_managed_session/v1"


@dataclass(frozen=True, slots=True)
class ManagedSessionRequest:
    label: str
    backend_id: str
    profile: str
    synthetic: bool
    source_command: tuple[str, ...]
    observer_command: tuple[str, ...]
    backend_command: tuple[str, ...]
    feedback_endpoint: str
    service_url: str
    working_directory: Path

    def __post_init__(self) -> None:
        if not self.label or not self.backend_id or not self.profile:
            raise ValueError("label, backend_id, and profile must be non-empty")
        if not all((self.source_command, self.observer_command, self.backend_command)):
            raise ValueError("source, observer, and backend commands must be non-empty")
        if not self.working_directory.is_dir():
            raise ValueError("working_directory must exist")


def runtime_dir() -> Path:
    configured = os.environ.get("EMBODIED_TELEOP_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(tempfile.gettempdir()) / f"embodied-teleop-{os.getuid()}"


def _state_path() -> Path:
    return runtime_dir() / "session.json"


def _log_path() -> Path:
    return runtime_dir() / "session.log"


@contextmanager
def _lock() -> Iterator[None]:
    runtime_dir().mkdir(parents=True, exist_ok=True)
    with (runtime_dir() / "session.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_state() -> dict[str, Any] | None:
    try:
        value = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (
        value if isinstance(value, dict) and value.get("schema_version") == STATE_SCHEMA else None
    )


def _write_state(state: dict[str, Any]) -> None:
    runtime_dir().mkdir(parents=True, exist_ok=True)
    temporary = runtime_dir() / f"session.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(_state_path())


def _process(pid: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat=", "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    line = result.stdout.strip()
    if result.returncode != 0 or not line:
        return False, ""
    process_state, _, command = line.partition(" ")
    return "Z" not in process_state, command.strip()


def _managed(state: dict[str, Any]) -> bool:
    try:
        alive, command = _process(int(state["pid"]))
    except (KeyError, TypeError, ValueError):
        return False
    return alive and "embodied_ops.teleop.process_supervisor" in command


def _terminate(state: dict[str, Any], timeout: float) -> bool:
    if not _managed(state):
        return True
    pid = int(state["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process(pid)[0]:
            return True
        time.sleep(0.1)
    if _managed(state):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return not _process(pid)[0]


def _feedback(endpoint: str, timeout: float) -> dict[str, Any] | None:
    context = zmq.Context()
    receiver = TeleopFeedbackReceiver(context, endpoint)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            candidate = receiver.newest()
            if candidate is not None:
                value = candidate[0]
                return {
                    "backend": value.backend,
                    "episode_id": value.episode_id,
                    "frame_index": value.frame_index,
                    "status": value.status,
                    "streaming": value.gate_open,
                    "recording": value.recording,
                    "target_age_ms": value.target_age_ms,
                }
            time.sleep(0.05)
    finally:
        receiver.close()
        context.term()
    return None


def _state_for(request: ManagedSessionRequest) -> tuple[dict[str, Any], list[str]]:
    command = [
        sys.executable,
        "-m",
        "embodied_ops.teleop.process_supervisor",
        "--label",
        request.label,
        "--source-command",
        json.dumps(request.source_command),
        "--observer-command",
        json.dumps(request.observer_command),
        "--backend-command",
        json.dumps(request.backend_command),
    ]
    state = {
        "schema_version": STATE_SCHEMA,
        "session_id": str(uuid.uuid4()),
        "label": request.label,
        "backend": request.backend_id,
        "profile": request.profile,
        "synthetic": request.synthetic,
        "feedback_endpoint": request.feedback_endpoint,
        "service_url": request.service_url,
        "working_directory": str(request.working_directory.resolve()),
        "log_path": str(_log_path()),
        "command": command,
    }
    return state, command


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_session(request: ManagedSessionRequest, *, wait_seconds: float = 180.0) -> int:
    if wait_seconds <= 0:
        raise ValueError("wait_seconds must be positive")
    requested, command = _state_for(request)
    with _lock():
        existing = _read_state()
        if existing is not None and _managed(existing):
            if existing.get("command") == command:
                snapshot = status_snapshot(probe_timeout=min(wait_seconds, 0.6))
                if snapshot["state"] == "ready":
                    print(
                        f"ALREADY RUNNING {existing['label']} pid={existing['pid']} "
                        f"url={existing['service_url']}"
                    )
                    return 0
            print(
                f"START FAILED: {existing.get('label', 'teleoperation')} is already running "
                f"(pid {existing.get('pid')})"
            )
            return 1
        with _log_path().open("w", encoding="utf-8") as log:
            process = subprocess.Popen(  # noqa: S603 - validated argv only
                command,
                cwd=request.working_directory,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        requested.update({"pid": process.pid, "status": "starting", "started_at": _utc_now()})
        _write_state(requested)

    deadline = time.monotonic() + wait_seconds
    latest = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        candidate = _feedback(
            request.feedback_endpoint, min(0.25, max(0.05, deadline - time.monotonic()))
        )
        if candidate is not None:
            latest = candidate
        if latest is not None and is_foxglove_server_ready(request.service_url, timeout_sec=0.1):
            requested.update({"status": "ready", "ready_at": _utc_now(), "last_feedback": latest})
            with _lock():
                _write_state(requested)
            print(f"READY {request.label} pid={process.pid} profile={request.profile}")
            print(f"URL {request.service_url}")
            return 0
    _terminate(requested, 8.0)
    requested.update({"status": "failed", "stopped_at": _utc_now()})
    with _lock():
        _write_state(requested)
    print(f"START FAILED: {request.label} did not become ready")
    return 1


def status_snapshot(*, probe_timeout: float = 0.6) -> dict[str, Any]:
    state = _read_state()
    if state is None or not _managed(state):
        return {"schema_version": STATE_SCHEMA, "state": "stopped", "running": False}
    foxglove_ready = is_foxglove_server_ready(state["service_url"], timeout_sec=probe_timeout)
    feedback = _feedback(state["feedback_endpoint"], probe_timeout)
    return {
        "schema_version": STATE_SCHEMA,
        "state": "ready" if foxglove_ready and feedback is not None else "degraded",
        "running": True,
        "label": state.get("label"),
        "backend": state.get("backend"),
        "profile": state.get("profile"),
        "synthetic": state.get("synthetic"),
        "pid": state.get("pid"),
        "service_url": state.get("service_url"),
        "foxglove_ready": foxglove_ready,
        "backend_ready": feedback is not None,
        "feedback": feedback,
        "log_path": state.get("log_path"),
    }


def show_status(*, as_json: bool = False, probe_timeout: float = 0.6) -> int:
    snapshot = status_snapshot(probe_timeout=probe_timeout)
    if as_json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    elif not snapshot["running"]:
        print("STOPPED no managed teleoperation")
    else:
        feedback = snapshot.get("feedback") or {}
        details = []
        if feedback:
            details.extend(
                (
                    f"backend={feedback['status']}",
                    "streaming" if feedback["streaming"] else "held",
                    "recording" if feedback["recording"] else "not-recording",
                )
            )
        print(
            f"{snapshot['state'].upper()} {snapshot['label']} pid={snapshot['pid']} "
            + " ".join(details)
        )
        print(f"URL {snapshot['service_url']}")
    return 0 if snapshot["state"] == "ready" else 1


def stop_session(*, wait_seconds: float = 12.0) -> int:
    state = _read_state()
    if state is None or not _managed(state):
        print("STOPPED no managed teleoperation")
        return 0
    if not _terminate(state, wait_seconds):
        print(f"STOP FAILED: {state.get('label')} pid={state.get('pid')} is still alive")
        return 1
    state.update({"status": "stopped", "stopped_at": _utc_now()})
    with _lock():
        _write_state(state)
    print(f"STOPPED {state.get('label')} pid={state.get('pid')}")
    return 0


def show_logs(*, lines: int = 80) -> int:
    try:
        content = _log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        print(f"No session log at {_log_path()}")
        return 1
    print("\n".join(content[-lines:]))
    return 0
