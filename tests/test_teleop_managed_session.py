from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from embodied_ops.teleop.managed_session import ManagedSessionRequest
from embodied_ops.teleop.managed_session import _state_for


def test_managed_session_is_composed_from_opaque_commands(tmp_path: Path) -> None:
    request = ManagedSessionRequest(
        label="Example backend",
        backend_id="example",
        profile="calibrated-frame",
        synthetic=False,
        source_command=("source-adapter", "--bind", "tcp://127.0.0.1:8130"),
        observer_command=("observer", "--port", "8765"),
        backend_command=("backend", "--record"),
        feedback_endpoint="tcp://127.0.0.1:8131",
        service_url="ws://127.0.0.1:8765",
        working_directory=tmp_path,
    )

    state, command = _state_for(request)

    assert state["backend"] == "example"
    assert state["profile"] == "calibrated-frame"
    assert "quest" not in " ".join(command).lower()
    source_index = command.index("--source-command") + 1
    assert json.loads(command[source_index]) == list(request.source_command)


def test_managed_session_rejects_missing_commands(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="commands must be non-empty"):
        ManagedSessionRequest(
            label="Example",
            backend_id="example",
            profile="frame",
            synthetic=False,
            source_command=(),
            observer_command=("observer",),
            backend_command=("backend",),
            feedback_endpoint="tcp://127.0.0.1:8131",
            service_url="ws://127.0.0.1:8765",
            working_directory=tmp_path,
        )


def test_supervisor_fails_if_a_required_child_exits(tmp_path: Path) -> None:
    wait = [sys.executable, "-c", "import time; time.sleep(30)"]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "embodied_ops.teleop.process_supervisor",
            "--label",
            "unit",
            "--source-command",
            json.dumps([sys.executable, "-c", "pass"]),
            "--observer-command",
            json.dumps(wait),
            "--backend-command",
            json.dumps(wait),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )

    assert result.returncode == 1
    assert "source exited unexpectedly" in result.stderr
