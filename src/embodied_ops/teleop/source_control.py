"""Device-neutral, bounded source configuration RPC (separate from robot commands)."""

from __future__ import annotations

import json
from typing import Any

import zmq

DEFAULT_SOURCE_CONTROL_ENDPOINT = "tcp://127.0.0.1:8133"


def request_source_control(endpoint: str, payload: bytes, *, timeout_ms: int = 2000) -> dict[str, Any]:
    """One socket per call: SDK service workers never share a ZMQ socket."""
    try:
        if len(payload) > 8192:
            raise ValueError("Source request too large")
        request = json.loads(payload)
        if not isinstance(request, dict):
            raise ValueError("Expected a source request object")
        with zmq.Context() as context, context.socket(zmq.REQ) as socket:
            socket.setsockopt(zmq.LINGER, 0)
            socket.connect(endpoint)
            socket.send_json(request)
            if not socket.poll(timeout_ms):
                raise TimeoutError("Input source unavailable — check source connection")
            return socket.recv_json()
    except (OSError, ValueError, zmq.ZMQError) as exc:
        return {"accepted": False, "applied": False, "message": str(exc)}
