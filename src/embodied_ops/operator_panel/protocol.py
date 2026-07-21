"""Machine-readable child-process input and presentation events."""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import TypeAlias


PROTOCOL_ENV = "OPERATOR_PANEL_PROTOCOL"
_PROTOCOL_PREFIX = "@@OPERATOR_PANEL "
_PROGRESS_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_PROGRESS_MIN_INTERVAL_S = 0.25
_progress_lock = threading.Lock()
_last_progress: dict[str, tuple[float, str]] = {}


@dataclass(frozen=True)
class InputEvent:
    actions: tuple[str, ...]


@dataclass(frozen=True)
class ProgressEvent:
    progress_id: str
    label: str
    current: int | float
    total: int | float | None
    phase: str
    detail: str

    def as_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["id"] = payload.pop("progress_id")
        return payload


@dataclass(frozen=True)
class InvalidEvent:
    reason: str


PanelEvent: TypeAlias = InputEvent | ProgressEvent | InvalidEvent


def announce_input(actions: Iterable[str]) -> None:
    """Tell a supervising panel which input actions are currently safe."""

    if os.environ.get(PROTOCOL_ENV) != "1":
        return
    normalized = _normalize_actions(actions)
    print(
        _PROTOCOL_PREFIX + json.dumps({"input": normalized}, separators=(",", ":")),
        flush=True,
    )


def announce_progress(
    progress_id: str,
    label: str,
    current: int | float,
    total: int | float | None,
    *,
    phase: str = "",
    detail: str = "",
    force: bool = False,
) -> bool:
    """Publish the latest display-only progress and report panel mode."""

    if os.environ.get(PROTOCOL_ENV) != "1":
        return False
    event = _progress_event(
        {
            "id": progress_id,
            "label": label,
            "current": current,
            "total": total,
            "phase": phase,
            "detail": detail,
        }
    )
    payload = json.dumps(
        {"progress": event.as_json()},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    now = time.monotonic()
    with _progress_lock:
        previous = _last_progress.get(progress_id)
        should_emit = (
            force
            or previous is None
            or payload != previous[1]
            and now - previous[0] >= _PROGRESS_MIN_INTERVAL_S
        )
        if should_emit:
            _last_progress[progress_id] = (now, payload)
    if should_emit:
        print(_PROTOCOL_PREFIX + payload, flush=True)
    return True


def parse_event(line: str) -> PanelEvent | None:
    if not line.startswith(_PROTOCOL_PREFIX):
        return None
    try:
        payload = json.loads(line[len(_PROTOCOL_PREFIX) :])
    except json.JSONDecodeError:
        return InvalidEvent("invalid JSON")
    if not isinstance(payload, dict):
        return InvalidEvent("event must be an object")
    if set(payload) == {"input"}:
        actions = payload["input"]
        if not isinstance(actions, list):
            return InputEvent(())
        try:
            return InputEvent(_normalize_actions(actions))
        except ValueError:
            return InputEvent(())
    if set(payload) == {"progress"}:
        try:
            return _progress_event(payload["progress"])
        except ValueError as exc:
            return InvalidEvent(str(exc))
    return InvalidEvent("unsupported event shape")


def strip_protocol_events(value: str) -> str:
    """Remove machine-readable panel event lines while preserving other text."""

    return "".join(
        line
        for line in value.splitlines(keepends=True)
        if not line.rstrip("\r\n").startswith(_PROTOCOL_PREFIX)
    )


def _progress_event(value: object) -> ProgressEvent:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "label",
        "current",
        "total",
        "phase",
        "detail",
    }:
        raise ValueError("progress requires id, label, current, total, phase, detail")
    progress_id = value["id"]
    label = value["label"]
    phase = value["phase"]
    detail = value["detail"]
    if not isinstance(progress_id, str) or not _PROGRESS_ID.fullmatch(progress_id):
        raise ValueError("progress id must be a lower-case identifier")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("progress label must be non-empty")
    if not isinstance(phase, str) or not isinstance(detail, str):
        raise ValueError("progress phase and detail must be strings")
    current = _finite_number(value["current"], label="progress current")
    if current < 0:
        raise ValueError("progress current must be non-negative")
    raw_total = value["total"]
    total = None if raw_total is None else _finite_number(raw_total, label="progress total")
    if total is not None and (total <= 0 or current > total):
        raise ValueError("progress total must be positive and at least current")
    return ProgressEvent(progress_id, label.strip(), current, total, phase, detail)


def _finite_number(value: object, *, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def _normalize_actions(actions: Iterable[str]) -> tuple[str, ...]:
    values = tuple(actions)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("operator-panel input actions must be non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError("operator-panel input actions must not contain duplicates")
    return values
