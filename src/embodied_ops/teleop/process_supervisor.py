"""Own and fail together a source, observer, and teleoperation backend process."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from collections.abc import Sequence


def _command(value: str, name: str) -> list[str]:
    try:
        command = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} command is not valid JSON") from exc
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item for item in command)
    ):
        raise ValueError(f"{name} command must be a non-empty JSON string array")
    return command


def _close(children: Sequence[subprocess.Popen[bytes]], timeout: float = 5.0) -> None:
    for child in children:
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(child.poll() is None for child in children):
        time.sleep(0.05)
    for child in children:
        if child.poll() is None:
            child.kill()
    for child in children:
        try:
            child.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--source-command", required=True)
    parser.add_argument("--observer-command", required=True)
    parser.add_argument("--backend-command", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    commands = (
        _command(args.source_command, "source"),
        _command(args.observer_command, "observer"),
        _command(args.backend_command, "backend"),
    )
    children: list[subprocess.Popen[bytes]] = []
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    print(f"Teleoperation owner: {args.label}", flush=True)
    try:
        for command in commands:
            children.append(subprocess.Popen(command))  # noqa: S603
        while not stopping:
            for role, child in zip(("source", "observer", "backend"), children):
                status = child.poll()
                if status is None:
                    continue
                if role != "backend" and status == 0:
                    print(f"{role} exited unexpectedly", file=sys.stderr, flush=True)
                    return 1
                return status
            time.sleep(0.1)
    finally:
        _close(children)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
