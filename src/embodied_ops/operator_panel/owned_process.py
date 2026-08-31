"""Supervise one workflow and stop its process group when the panel owner disappears."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence


OWNER_PID_ENV = "EMBODIED_OPS_PANEL_OWNER_PID"
_INTERRUPT_GRACE_S = 8.0
_TERMINATE_GRACE_S = 2.0
_POLL_INTERVAL_S = 0.05


def owned_command(
    command: Sequence[str], *, owner_pid: int
) -> tuple[tuple[str, ...], dict[str, str]]:
    """Build the private supervisor argv and environment for a panel workflow."""

    normalized = tuple(str(item) for item in command)
    if not normalized:
        raise ValueError("workflow command must not be empty")
    if owner_pid <= 1:
        raise ValueError("workflow owner pid must identify a live user process")
    return (
        (sys.executable, "-m", "embodied_ops.operator_panel.owned_process", *normalized),
        {OWNER_PID_ENV: str(owner_pid)},
    )


def main(argv: Sequence[str] | None = None) -> int:
    command = tuple(sys.argv[1:] if argv is None else argv)
    if not command:
        raise SystemExit("owned workflow command must not be empty")
    owner_pid = _owner_pid()
    parent_lost = False
    interrupted = False

    def request_parent_loss(_signum: int, _frame: object) -> None:
        nonlocal parent_lost
        parent_lost = True

    def request_interrupt(_signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGTERM, request_parent_loss)
    signal.signal(signal.SIGINT, request_interrupt)
    _install_linux_parent_death_signal()
    if os.getppid() != owner_pid:
        return 125

    child = subprocess.Popen(command, start_new_session=True)
    interrupt_at: float | None = None
    terminate_at: float | None = None
    kill_at: float | None = None
    while True:
        return_code = child.poll()
        if return_code is not None:
            return _shell_return_code(return_code)

        if os.getppid() != owner_pid:
            parent_lost = True
        if parent_lost or interrupted:
            now = time.monotonic()
            if interrupt_at is None:
                _signal_process_group(child.pid, signal.SIGINT)
                interrupt_at = now
                terminate_at = now + _INTERRUPT_GRACE_S
                kill_at = terminate_at + _TERMINATE_GRACE_S
            elif terminate_at is not None and now >= terminate_at:
                _signal_process_group(child.pid, signal.SIGTERM)
                terminate_at = None
            elif kill_at is not None and now >= kill_at:
                _signal_process_group(child.pid, signal.SIGKILL)
                kill_at = None
        time.sleep(_POLL_INTERVAL_S)


def _owner_pid() -> int:
    raw = os.environ.pop(OWNER_PID_ENV, "")
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{OWNER_PID_ENV} must be an integer") from exc
    if value <= 1:
        raise SystemExit(f"{OWNER_PID_ENV} must identify a live user process")
    return value


def _install_linux_parent_death_signal() -> None:
    if not sys.platform.startswith("linux"):
        return
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.prctl(1, int(signal.SIGTERM), 0, 0, 0)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _signal_process_group(pid: int, signum: signal.Signals) -> None:
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        return


def _shell_return_code(return_code: int) -> int:
    return return_code if return_code >= 0 else 128 + abs(return_code)


if __name__ == "__main__":
    raise SystemExit(main())
