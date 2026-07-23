"""Normalized camera-health presentation contract."""

from __future__ import annotations

import json
import math
from http.client import HTTPConnection
from typing import Any

DEFAULT_TIMEOUT_S = 0.4
DEFAULT_MAX_BYTES = 64 * 1024


def fetch_camera_health(
    port: int,
    *,
    host: str = "127.0.0.1",
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Fetch and normalize a local read-only camera health endpoint."""

    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("camera health port must be an integer in [1, 65535]")
    if not isinstance(host, str) or not host:
        raise ValueError("camera health host must be non-empty text")
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("camera health timeout must be finite and positive")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("camera health maximum response size must be positive")

    connection = HTTPConnection(host, port, timeout=timeout_s)
    try:
        connection.request("GET", "/healthz", headers={"Cache-Control": "no-store"})
        response = connection.getresponse()
        body = response.read(max_bytes + 1)
    except (OSError, TimeoutError):
        return unavailable_camera_health("Camera service is not running.")
    finally:
        connection.close()
    if len(body) > max_bytes:
        return unavailable_camera_health("Camera health response is too large.")
    if response.status not in {200, 503}:
        return unavailable_camera_health("Camera health request failed.")
    try:
        return normalize_camera_health(json.loads(body))
    except (json.JSONDecodeError, TypeError, ValueError):
        return unavailable_camera_health("Camera service returned invalid health data.")


def normalize_camera_health(payload: Any) -> dict[str, Any]:
    """Validate the repository camera service response for Panel presentation."""

    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise ValueError("camera health must contain a boolean ok value")
    raw_streams = payload.get("streams")
    if not isinstance(raw_streams, dict):
        raise ValueError("camera health streams must be an object")
    streams: dict[str, dict[str, Any]] = {}
    for stream_id, raw in raw_streams.items():
        if not isinstance(stream_id, str) or not stream_id or not isinstance(raw, dict):
            raise ValueError("camera health stream is invalid")
        ready = raw.get("ready")
        fresh = raw.get("fresh")
        error = raw.get("error")
        if not isinstance(ready, bool) or not isinstance(fresh, bool):
            raise ValueError("camera health readiness values must be booleans")
        if error is not None and not isinstance(error, str):
            raise ValueError("camera health error must be text or null")
        streams[stream_id] = {
            "ready": ready,
            "fresh": fresh,
            "preview_fps": _optional_nonnegative_number(
                raw.get("preview_fps"), label="preview_fps"
            ),
            "age_s": _optional_nonnegative_number(raw.get("age_s"), label="age_s"),
            "error": error,
        }
    return {"available": True, "ok": payload["ok"], "streams": streams}


def unavailable_camera_health(reason: str) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason:
        raise ValueError("camera health reason must be non-empty text")
    return {"available": False, "ok": False, "streams": {}, "reason": reason}


def _optional_nonnegative_number(value: Any, *, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"camera health {label} must be numeric or null")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"camera health {label} must be finite and non-negative")
    return number
