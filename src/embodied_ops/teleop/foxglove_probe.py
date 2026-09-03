"""Protocol-level readiness probe for the canonical Foxglove WebSocket gateway."""

from __future__ import annotations

import argparse
import json
import time

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

FOXGLOVE_SUBPROTOCOL = "foxglove.sdk.v1"
DEFAULT_SERVER_NAME = "Embodied teleoperation"


def is_foxglove_server_ready(
    url: str,
    *,
    timeout_sec: float = 0.25,
    expected_server_name: str = DEFAULT_SERVER_NAME,
) -> bool:
    """Return true only after a Foxglove handshake and matching serverInfo."""

    timeout_sec = max(0.01, float(timeout_sec))
    deadline = time.monotonic() + timeout_sec
    try:
        with connect(
            url,
            subprotocols=[FOXGLOVE_SUBPROTOCOL],
            open_timeout=timeout_sec,
            close_timeout=timeout_sec,
            proxy=None,
        ) as websocket:
            if websocket.subprotocol != FOXGLOVE_SUBPROTOCOL:
                return False
            while (remaining := deadline - time.monotonic()) > 0:
                message = websocket.recv(timeout=remaining)
                if not isinstance(message, str):
                    continue
                payload = json.loads(message)
                if payload.get("op") == "serverInfo":
                    return payload.get("name") == expected_server_name
    except (OSError, TimeoutError, ValueError, WebSocketException):
        return False
    return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--timeout-sec", type=float, default=0.25)
    parser.add_argument("--expected-server-name", default=DEFAULT_SERVER_NAME)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return (
        0
        if is_foxglove_server_ready(
            args.url,
            timeout_sec=args.timeout_sec,
            expected_server_name=args.expected_server_name,
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
