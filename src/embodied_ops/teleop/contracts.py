"""Strict, source-neutral contracts for Cartesian teleoperation."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

TARGET_SCHEMA = "embodied.teleop_target/v1"
FEEDBACK_SCHEMA = "embodied.teleop_feedback/v1"
COMMAND_SCHEMA = "embodied.teleop_command/v1"
COMMAND_RESULT_SCHEMA = "embodied.teleop_command_result/v1"


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be non-empty text")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _optional_integer(value: object, label: str) -> int | None:
    return None if value is None else _integer(value, label)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _optional_number(value: object, label: str) -> float | None:
    return None if value is None else _number(value, label)


def _vector(value: object, length: int, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"{label} must contain {length} finite numbers")
    return [_number(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _matrix3(value: object, label: str) -> list[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must be a 3x3 matrix")
    return [_vector(row, 3, f"{label}[{index}]") for index, row in enumerate(value)]


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class TeleopTarget:
    """Latest desired Cartesian pose, independent of the input device."""

    seq: int
    timestamp: float
    position: list[float]
    rotation: list[list[float]]
    gripper: float
    gate_open: bool
    source: str = "unknown"
    session_id: str = "unspecified"
    frame_id: int | None = None
    host_received_monotonic_ns: int | None = None
    host_published_unix_ns: int | None = None
    tracking_valid: bool = True
    source_metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = TARGET_SCHEMA

    def __post_init__(self) -> None:
        _integer(self.seq, "target seq")
        _number(self.timestamp, "target timestamp")
        _vector(self.position, 3, "target position")
        _matrix3(self.rotation, "target rotation")
        gripper = _number(self.gripper, "target gripper")
        if not -1.0 <= gripper <= 1.0:
            raise ValueError("target gripper must be within [-1, 1]")
        _boolean(self.gate_open, "target gate_open")
        _text(self.source, "target source")
        _text(self.session_id, "target session_id")
        _optional_integer(self.frame_id, "target frame_id")
        _optional_integer(self.host_received_monotonic_ns, "target host_received_monotonic_ns")
        _optional_integer(self.host_published_unix_ns, "target host_published_unix_ns")
        _boolean(self.tracking_valid, "target tracking_valid")
        _object(self.source_metadata, "target source_metadata")
        if self.schema_version != TARGET_SCHEMA:
            raise ValueError(f"unsupported emitted target schema: {self.schema_version}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "position": list(self.position),
            "rotation": [list(row) for row in self.rotation],
            "gripper": self.gripper,
            "gate_open": self.gate_open,
            "source": self.source,
            "session_id": self.session_id,
            "frame_id": self.frame_id,
            "host_received_monotonic_ns": self.host_received_monotonic_ns,
            "host_published_unix_ns": self.host_published_unix_ns,
            "tracking_valid": self.tracking_valid,
            "source_metadata": dict(self.source_metadata),
        }

    def to_json(self) -> str:
        return _json_bytes(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TeleopTarget:
        value = _object(raw, "teleop target")
        schema = value.get("schema_version")
        if schema != TARGET_SCHEMA:
            raise ValueError(f"unsupported teleop target schema: {schema}")
        metadata = _object(value.get("source_metadata", {}), "target source_metadata")
        return cls(
            seq=_integer(value["seq"], "target seq"),
            timestamp=_number(value["timestamp"], "target timestamp"),
            position=_vector(value["position"], 3, "target position"),
            rotation=_matrix3(value["rotation"], "target rotation"),
            gripper=_number(value["gripper"], "target gripper"),
            gate_open=_boolean(value["gate_open"], "target gate_open"),
            source=_text(value.get("source", "quest"), "target source"),
            session_id=_text(value.get("session_id", "unspecified"), "target session_id"),
            frame_id=_optional_integer(value.get("frame_id"), "target frame_id"),
            host_received_monotonic_ns=_optional_integer(
                value.get("host_received_monotonic_ns"),
                "target host_received_monotonic_ns",
            ),
            host_published_unix_ns=_optional_integer(
                value.get("host_published_unix_ns"), "target host_published_unix_ns"
            ),
            tracking_valid=_boolean(value.get("tracking_valid", True), "target tracking_valid"),
            source_metadata=metadata,
        )

    @classmethod
    def from_json(cls, payload: bytes | str) -> TeleopTarget:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        return cls.from_dict(_object(json.loads(text), "teleop target"))

    def _metadata(self, name: str, default: Any = None) -> Any:
        return self.source_metadata.get(name, default)

    @property
    def raw_position(self) -> list[float]:
        return _vector(self._metadata("raw_position", self.position), 3, "raw_position")

    @property
    def raw_rotation(self) -> list[float]:
        return _vector(
            self._metadata("raw_rotation", [0.0, 0.0, 0.0, 1.0]),
            4,
            "raw_rotation",
        )

    @property
    def flag(self) -> bool:
        return bool(self._metadata("flag", False))

    @property
    def pause_state(self) -> str | None:
        value = self._metadata("pause_state")
        return None if value is None else str(value)

    @property
    def remote_count(self) -> int:
        return int(self._metadata("remote_count", self.frame_id or 0))

    @property
    def controller_id(self) -> str:
        return str(self._metadata("controller_id", "unknown"))

    @property
    def calibration_id(self) -> str | None:
        value = self._metadata("calibration_id")
        return None if value is None else str(value)

    @property
    def calibration_sha256(self) -> str | None:
        value = self._metadata("calibration_sha256")
        return None if value is None else str(value)


@dataclass(frozen=True, slots=True)
class TeleopFeedback:
    """One action-aligned backend sample plus separately transported cameras."""

    backend: str
    episode_id: str
    frame_index: int
    status: str
    target_seq: int | None
    target_age_ms: float | None
    gate_open: bool
    recording: bool
    eef_position: list[float]
    gripper: float
    action: list[float]
    eef_orientation_xyzw: list[float] | None = None
    desired_eef_position: list[float] | None = None
    desired_eef_orientation_xyzw: list[float] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    timestamp_unix_ns: int = field(default_factory=time.time_ns)
    monotonic_ns: int = field(default_factory=time.monotonic_ns)
    schema_version: str = FEEDBACK_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "episode_id": self.episode_id,
            "frame_index": self.frame_index,
            "status": self.status,
            "target_seq": self.target_seq,
            "target_age_ms": self.target_age_ms,
            "gate_open": self.gate_open,
            "recording": self.recording,
            "eef_position": list(self.eef_position),
            "eef_orientation_xyzw": (
                None if self.eef_orientation_xyzw is None else list(self.eef_orientation_xyzw)
            ),
            "desired_eef_position": (
                None if self.desired_eef_position is None else list(self.desired_eef_position)
            ),
            "desired_eef_orientation_xyzw": (
                None
                if self.desired_eef_orientation_xyzw is None
                else list(self.desired_eef_orientation_xyzw)
            ),
            "gripper": self.gripper,
            "action": list(self.action),
            "diagnostics": dict(self.diagnostics),
            "timestamp_unix_ns": self.timestamp_unix_ns,
            "monotonic_ns": self.monotonic_ns,
        }

    def to_json(self) -> bytes:
        return _json_bytes(self.to_dict())

    @classmethod
    def from_json(cls, payload: bytes | str) -> TeleopFeedback:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        value = _object(json.loads(text), "teleop feedback")
        schema = value.get("schema_version")
        if schema != FEEDBACK_SCHEMA:
            raise ValueError(f"unsupported teleop feedback schema: {schema}")
        return cls(
            backend=_text(value["backend"], "feedback backend"),
            episode_id=_text(value["episode_id"], "feedback episode_id"),
            frame_index=_integer(value["frame_index"], "feedback frame_index"),
            status=_text(value["status"], "feedback status"),
            target_seq=_optional_integer(value.get("target_seq"), "feedback target_seq"),
            target_age_ms=_optional_number(value.get("target_age_ms"), "feedback target_age_ms"),
            gate_open=_boolean(value["gate_open"], "feedback gate_open"),
            recording=_boolean(value["recording"], "feedback recording"),
            eef_position=_vector(value["eef_position"], 3, "feedback eef_position"),
            eef_orientation_xyzw=(
                None
                if value.get("eef_orientation_xyzw") is None
                else _vector(
                    value["eef_orientation_xyzw"],
                    4,
                    "feedback eef_orientation_xyzw",
                )
            ),
            desired_eef_position=(
                None
                if value.get("desired_eef_position") is None
                else _vector(
                    value["desired_eef_position"],
                    3,
                    "feedback desired_eef_position",
                )
            ),
            desired_eef_orientation_xyzw=(
                None
                if value.get("desired_eef_orientation_xyzw") is None
                else _vector(
                    value["desired_eef_orientation_xyzw"],
                    4,
                    "feedback desired_eef_orientation_xyzw",
                )
            ),
            gripper=_number(value["gripper"], "feedback gripper"),
            action=[
                _number(item, f"feedback action[{index}]")
                for index, item in enumerate(value["action"])
            ],
            diagnostics=_object(value.get("diagnostics", {}), "feedback diagnostics"),
            timestamp_unix_ns=_integer(value["timestamp_unix_ns"], "feedback timestamp_unix_ns"),
            monotonic_ns=_integer(value["monotonic_ns"], "feedback monotonic_ns"),
        )


@dataclass(frozen=True, slots=True)
class TeleopCommand:
    """Idempotent operator request; the backend remains the safety authority."""

    command: str
    request_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    issued_unix_ns: int = field(default_factory=time.time_ns)
    schema_version: str = COMMAND_SCHEMA

    def to_json(self) -> bytes:
        return _json_bytes(
            {
                "schema_version": self.schema_version,
                "command": self.command,
                "request_id": self.request_id,
                "arguments": dict(self.arguments),
                "issued_unix_ns": self.issued_unix_ns,
            }
        )

    @classmethod
    def from_json(cls, payload: bytes | str) -> TeleopCommand:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        value = _object(json.loads(text), "teleop command")
        schema = value.get("schema_version")
        if schema != COMMAND_SCHEMA:
            raise ValueError(f"unsupported teleop command schema: {schema}")
        return cls(
            command=_text(value["command"], "command name"),
            request_id=_text(value["request_id"], "command request_id"),
            arguments=_object(value.get("arguments", {}), "command arguments"),
            issued_unix_ns=_integer(value["issued_unix_ns"], "command issued_unix_ns"),
        )


@dataclass(frozen=True, slots=True)
class TeleopCommandResult:
    """Backend acknowledgement for one idempotent operator request."""

    request_id: str
    command: str
    accepted: bool
    applied: bool
    backend: str
    message: str = ""
    duplicate: bool = False
    completed_unix_ns: int = field(default_factory=time.time_ns)
    schema_version: str = COMMAND_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "command": self.command,
            "accepted": self.accepted,
            "applied": self.applied,
            "backend": self.backend,
            "message": self.message,
            "duplicate": self.duplicate,
            "completed_unix_ns": self.completed_unix_ns,
        }

    def to_json(self) -> bytes:
        return _json_bytes(self.to_dict())

    @classmethod
    def from_json(cls, payload: bytes | str) -> TeleopCommandResult:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        value = _object(json.loads(text), "teleop command result")
        if value.get("schema_version") != COMMAND_RESULT_SCHEMA:
            raise ValueError("unsupported teleop command-result schema")
        return cls(
            request_id=_text(value["request_id"], "result request_id"),
            command=_text(value["command"], "result command"),
            accepted=_boolean(value["accepted"], "result accepted"),
            applied=_boolean(value["applied"], "result applied"),
            backend=_text(value["backend"], "result backend"),
            message=str(value.get("message", "")),
            duplicate=_boolean(value.get("duplicate", False), "result duplicate"),
            completed_unix_ns=_integer(value["completed_unix_ns"], "result completed_unix_ns"),
        )
