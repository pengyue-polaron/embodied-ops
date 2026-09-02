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
PROTOCOL_VERSION_ENV = "OPERATOR_PANEL_PROTOCOL_VERSION"
PANEL_EVENT_SCHEMA_VERSION = 2
_SUPPORTED_EVENT_SCHEMA_VERSIONS = {1, PANEL_EVENT_SCHEMA_VERSION}
_PROTOCOL_PREFIX = "@@OPERATOR_PANEL "
_PROGRESS_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_INPUT_PHASE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PROGRESS_MIN_INTERVAL_S = 0.25
_progress_lock = threading.Lock()
_last_progress: dict[str, tuple[float, str]] = {}


@dataclass(frozen=True)
class InputEvent:
    actions: tuple[str, ...]
    phase: str = ""
    detail: str = ""


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


def announce_input(
    actions: Iterable[str],
    *,
    phase: str = "",
    detail: str = "",
) -> None:
    """Tell a supervising panel which input actions are currently safe."""

    if os.environ.get(PROTOCOL_ENV) != "1":
        return
    normalized = _normalize_actions(actions)
    normalized_phase, normalized_detail = _normalize_input_context(phase, detail)
    print(
        _PROTOCOL_PREFIX
        + _encode_event(
            {
                "input": {
                    "actions": normalized,
                    "phase": normalized_phase,
                    "detail": normalized_detail,
                }
            }
        ),
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
    payload = _encode_event({"progress": event.as_json()})
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
    schema_version: int | None = None
    if set(payload) == {"schema_version", "event"}:
        schema_version = payload["schema_version"]
        if schema_version not in _SUPPORTED_EVENT_SCHEMA_VERSIONS:
            return InvalidEvent("unsupported event schema version")
        payload = payload["event"]
        if not isinstance(payload, dict):
            return InvalidEvent("versioned event payload must be an object")
    if set(payload) == {"input"}:
        try:
            return _input_event(payload["input"], schema_version=schema_version)
        except ValueError as exc:
            return InvalidEvent(str(exc))
    if set(payload) == {"progress"}:
        try:
            return _progress_event(payload["progress"])
        except ValueError as exc:
            return InvalidEvent(str(exc))
    return InvalidEvent("unsupported event shape")


def _input_event(value: object, *, schema_version: int | None) -> InputEvent:
    if isinstance(value, list):
        return InputEvent(_normalize_actions(value))
    if schema_version != PANEL_EVENT_SCHEMA_VERSION or not isinstance(value, dict):
        raise ValueError("input actions must be a list")
    if set(value) != {"actions", "phase", "detail"}:
        raise ValueError("versioned input event must contain actions, phase, and detail")
    actions = value["actions"]
    if not isinstance(actions, list):
        raise ValueError("input actions must be a list")
    phase, detail = _normalize_input_context(value["phase"], value["detail"])
    return InputEvent(_normalize_actions(actions), phase=phase, detail=detail)


def _normalize_input_context(phase: object, detail: object) -> tuple[str, str]:
    if not isinstance(phase, str) or (phase and _INPUT_PHASE.fullmatch(phase) is None):
        raise ValueError("input phase must be empty or a lowercase identifier")
    if not isinstance(detail, str) or "\x00" in detail or len(detail.encode("utf-8")) > 1024:
        raise ValueError("input detail must be text of at most 1024 UTF-8 bytes without NUL")
    return phase, detail


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


def _encode_event(event: dict[str, object]) -> str:
    return json.dumps(
        {"schema_version": PANEL_EVENT_SCHEMA_VERSION, "event": event},
        separators=(",", ":"),
        ensure_ascii=False,
    )
