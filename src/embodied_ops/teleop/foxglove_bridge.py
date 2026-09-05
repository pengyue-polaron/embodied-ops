"""Expose the canonical ZMQ teleoperation plane through Foxglove WebSocket."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import zmq
from .controller_scene import ControllerScene
from . import (
    TeleopCommand,
    TeleopCommandName,
    TeleopCommandResult,
    TeleopFeedback,
    TeleopSourceStatus,
    TeleopTarget,
    matrix_to_quat_xyzw,
)
from .zmq_transport import (
    DEFAULT_COMMAND_ENDPOINT,
    DEFAULT_FEEDBACK_ENDPOINT,
    DEFAULT_STATUS_TOPIC,
    DEFAULT_TARGET_ENDPOINT,
    DEFAULT_TARGET_TOPIC,
    TeleopCommandClient,
    TeleopFeedbackReceiver,
)
from foxglove.channels import CompressedImageChannel, PoseInFrameChannel, SceneUpdateChannel
from foxglove.messages import (
    CompressedImage,
    Pose,
    PoseInFrame,
    Quaternion,
    Timestamp,
    Vector3,
)
from foxglove.websocket import Capability, ServiceRequest
from .source_control import DEFAULT_SOURCE_CONTROL_ENDPOINT, request_source_control

import foxglove
from foxglove import MessageSchema, Schema, Service, ServiceSchema

SERVICE_COMMANDS = {
    "/teleop/hold": TeleopCommandName.HOLD.value,
    "/teleop/resume": TeleopCommandName.RESUME.value,
    "/teleop/episode/previous": TeleopCommandName.PREVIOUS_EPISODE.value,
    "/teleop/episode/reset": TeleopCommandName.RESET_EPISODE.value,
    "/teleop/episode/next": TeleopCommandName.NEXT_EPISODE.value,
    "/teleop/recording/start": TeleopCommandName.START_RECORDING.value,
    "/teleop/recording/stop": TeleopCommandName.STOP_RECORDING.value,
    "/teleop/recording/retry-stage": TeleopCommandName.RETRY_RECORDING_STAGE.value,
    "/teleop/recording/discard": TeleopCommandName.DISCARD_RECORDING.value,
}

COMMAND_TIMEOUT_MS = {
    TeleopCommandName.RESET_EPISODE.value: 30_000,
    TeleopCommandName.PREVIOUS_EPISODE.value: 30_000,
    TeleopCommandName.NEXT_EPISODE.value: 30_000,
    # Some backends use Save as a transactional phase boundary and must reset
    # a simulator plus its isolated camera renderer before acknowledging it.
    TeleopCommandName.STOP_RECORDING.value: 30_000,
    TeleopCommandName.RETRY_RECORDING_STAGE.value: 30_000,
}

DEFAULT_FOXGLOVE_LAYOUT_ID = ""

TELEMETRY_SCHEMA = {
    "type": "object",
    "properties": {
        "backend": {"type": "string"},
        "episode_id": {"type": "string"},
        "frame_index": {"type": "integer"},
        "status": {"type": "string"},
        "target_seq": {"type": ["integer", "null"]},
        "target_age_ms": {"type": ["number", "null"]},
        "gate_open": {"type": "boolean"},
        "recording": {"type": "boolean"},
        "eef_x_m": {"type": "number"},
        "eef_y_m": {"type": "number"},
        "eef_z_m": {"type": "number"},
        "gripper": {"type": "number"},
        "action_0": {"type": ["number", "null"]},
        "action_1": {"type": ["number", "null"]},
        "action_2": {"type": ["number", "null"]},
        "action_3": {"type": ["number", "null"]},
        "action_4": {"type": ["number", "null"]},
        "action_5": {"type": ["number", "null"]},
        "action_6": {"type": ["number", "null"]},
        "force_x_N": {"type": ["number", "null"]},
        "force_y_N": {"type": ["number", "null"]},
        "force_z_N": {"type": ["number", "null"]},
        "force_norm_N": {"type": ["number", "null"]},
        "torque_x_Nm": {"type": ["number", "null"]},
        "torque_y_Nm": {"type": ["number", "null"]},
        "torque_z_Nm": {"type": ["number", "null"]},
        "torque_norm_Nm": {"type": ["number", "null"]},
        "wrench_bias_ready": {"type": ["boolean", "null"]},
        "diagnostics": {"type": "object"},
    },
    "additionalProperties": True,
}

DIAGNOSTIC_ARRAY_SCHEMA = {
    "type": "object",
    "properties": {
        "header": {
            "type": "object",
            "properties": {
                "stamp": {
                    "type": "object",
                    "properties": {
                        "sec": {"type": "integer"},
                        "nanosec": {"type": "integer"},
                    },
                    "required": ["sec", "nanosec"],
                },
                "frame_id": {"type": "string"},
            },
            "required": ["stamp", "frame_id"],
        },
        "status": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer"},
                    "name": {"type": "string"},
                    "message": {"type": "string"},
                    "hardware_id": {"type": "string"},
                    "values": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["key", "value"],
                        },
                    },
                },
                "required": ["level", "name", "message", "hardware_id", "values"],
            },
        },
    },
    "required": ["header", "status"],
}

OPERATOR_STATE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "severity": {"type": "string", "enum": ["ok", "warn", "error", "stale"]},
        "source": {"type": "string"},
        # Kept for desktop clients that cached extension 1.1 before the generic
        # source label was introduced. New clients render ``source`` only.
        "quest": {"type": "string"},
        "controller": {"type": "string"},
        "backend": {"type": "string"},
        "view": {"type": "string"},
        "controller_position_m": {
            "type": ["array", "null"],
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
        },
        "gate_open": {"type": "boolean"},
        "recording": {"type": "boolean"},
        "episode_id": {"type": ["string", "null"]},
        "recording_phase": {"type": ["string", "null"]},
        "active_agent": {"type": ["string", "null"]},
        "replay_index": {"type": ["integer", "null"]},
        "replay_frame_count": {"type": ["integer", "null"]},
        "calibration_editor": {"type": ["object", "null"], "additionalProperties": True},
    },
    "required": [
        "status",
        "severity",
        "source",
        "controller",
        "backend",
        "view",
        "controller_position_m",
        "gate_open",
        "recording",
        "episode_id",
        "recording_phase",
        "active_agent",
        "replay_index",
        "replay_frame_count",
    ],
}

DIAGNOSTIC_OK = 0
DIAGNOSTIC_WARN = 1
DIAGNOSTIC_ERROR = 2
DIAGNOSTIC_STALE = 3

_SOURCE_STALE_SEC = 2.5
_BACKEND_STALE_SEC = 1.0


def _display(value: Any, *, none: str = "—") -> str:
    if value is None:
        return none
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _values(items: list[tuple[str, Any]]) -> list[dict[str, str]]:
    return [{"key": key, "value": _display(value)} for key, value in items]


def _diagnostic_status(
    name: str,
    level: int,
    message: str,
    values: list[tuple[str, Any]],
) -> dict[str, Any]:
    return {
        "level": level,
        "name": name,
        "message": message,
        # Preserve the stable selector used by existing Foxglove layouts.
        "hardware_id": "quest-teleop",
        "values": _values(values),
    }


def diagnostic_array(
    *,
    timestamp_ns: int,
    source_status: dict[str, Any] | None,
    source_age_sec: float | None,
    target: TeleopTarget | None,
    target_age_sec: float | None,
    feedback: TeleopFeedback | None,
    feedback_age_sec: float | None,
) -> dict[str, Any]:
    """Build one compact operator status for Foxglove's Diagnostics panel."""
    target_fresh = target is not None and target_age_sec is not None and target_age_sec <= 0.5
    status_fresh = bool(
        source_status is not None
        and source_age_sec is not None
        and source_age_sec <= _SOURCE_STALE_SEC
    )
    source_stale = not target_fresh and not status_fresh
    source = source_status or {}
    source_metadata = source.get("source_metadata", {})
    source_name = str(source.get("source") or (target.source if target is not None else "input"))
    synthetic_source = source_name == "synthetic"
    if synthetic_source:
        tracking_valid = stream_online = adb_online = app_resumed = True
    elif status_fresh:
        tracking_valid = bool(source.get("tracking_valid"))
        stream_online = bool(source.get("stream_online"))
        adb_online = bool(source_metadata.get("adb_connected"))
        app_resumed = bool(source_metadata.get("app_resumed"))
    else:
        tracking_valid = bool(target_fresh and target is not None and target.tracking_valid)
        stream_online = adb_online = app_resumed = target_fresh
    pause_state = source.get("pause_state")
    gate_known = bool(
        target_fresh or synthetic_source or (status_fresh and pause_state in {"High", "Low"})
    )
    gate_open = bool(
        target.gate_open if target_fresh and target is not None else source.get("gate_open")
    )
    source_online = bool(adb_online or stream_online)
    app_active = bool(app_resumed or stream_online)

    if source_stale:
        level = DIAGNOSTIC_STALE
        message = "Disconnected"
    elif not source_online:
        level = DIAGNOSTIC_ERROR
        message = "Disconnected"
    elif not app_active:
        level = DIAGNOSTIC_ERROR
        message = "Disconnected"
    elif (target.source_metadata if target_fresh and target is not None else source_metadata).get(
        "calibration_valid"
    ) is False:
        level = DIAGNOSTIC_WARN if tracking_valid and target_fresh else DIAGNOSTIC_ERROR
        message = "Calibrating" if tracking_valid and target_fresh else "Disconnected"
    elif gate_known and not gate_open:
        level = DIAGNOSTIC_WARN
        message = "Paused"
    elif not gate_known or not stream_online or not target_fresh or not tracking_valid:
        level = DIAGNOSTIC_ERROR
        message = "Disconnected"
    else:
        level = DIAGNOSTIC_OK
        message = "Streaming"

    if synthetic_source:
        source_label = "Synthetic · Online"
    elif source_stale or not source_online:
        source_label = f"{source_name.title()} · Offline"
    else:
        source_label = f"{source_name.title()} · Online"

    if target_fresh and target is not None and target.tracking_valid:
        x, y, z = target.position
        position_label = f"x {x:+.3f}  y {y:+.3f}  z {z:+.3f}"
    else:
        position_label = "Unavailable"

    statuses = [
        _diagnostic_status(
            "Teleop/Controller",
            level,
            message,
            [
                ("Controller state", message),
                ("Controller pose (m)", position_label),
                ("Input source", source_label),
            ],
        )
    ]
    return {
        "header": {
            "stamp": {
                "sec": timestamp_ns // 1_000_000_000,
                "nanosec": timestamp_ns % 1_000_000_000,
            },
            "frame_id": "teleop_world",
        },
        "status": statuses,
    }


def operator_state(
    *,
    timestamp_ns: int,
    source_status: dict[str, Any] | None,
    source_age_sec: float | None,
    target: TeleopTarget | None,
    target_age_sec: float | None,
    feedback: TeleopFeedback | None,
    feedback_age_sec: float | None,
) -> dict[str, Any]:
    """Return the terse, typed state consumed by the React operator panel."""

    diagnostics = diagnostic_array(
        timestamp_ns=timestamp_ns,
        source_status=source_status,
        source_age_sec=source_age_sec,
        target=target,
        target_age_sec=target_age_sec,
        feedback=feedback,
        feedback_age_sec=feedback_age_sec,
    )["status"][0]
    values = {item["key"]: item["value"] for item in diagnostics["values"]}
    level = int(diagnostics["level"])
    severity = {
        DIAGNOSTIC_OK: "ok",
        DIAGNOSTIC_WARN: "warn",
        DIAGNOSTIC_ERROR: "error",
        DIAGNOSTIC_STALE: "stale",
    }.get(level, "error")
    target_fresh = target is not None and target_age_sec is not None and target_age_sec <= 0.5
    position = (
        [float(item) for item in target.position]
        if target_fresh and target is not None and target.tracking_valid
        else None
    )
    controller = str(values.get("Controller state", "Disconnected"))

    feedback_fresh = bool(
        feedback is not None
        and feedback_age_sec is not None
        and feedback_age_sec <= _BACKEND_STALE_SEC
    )
    if feedback_fresh and feedback is not None:
        backend = feedback.backend
        loop_hz = feedback.diagnostics.get("loop_hz")
        if isinstance(loop_hz, (int, float)):
            backend += f" · {float(loop_hz):.0f} Hz"
        camera_age_ms = feedback.diagnostics.get("camera_age_ms")
        if isinstance(camera_age_ms, (int, float)):
            effective_age_ms = float(camera_age_ms) + float(feedback_age_sec or 0.0) * 1000.0
            view_state = "Live" if effective_age_ms <= 125.0 else "Delayed"
            view = f"{view_state} · {effective_age_ms:.0f} ms"
        else:
            view = "Waiting"
    else:
        backend = "Offline"
        view = "Offline"

    source_label = str(values.get("Input source", "Input · Offline"))
    feedback_diagnostics = feedback.diagnostics if feedback_fresh and feedback else {}
    recording_phase = feedback_diagnostics.get("recording_phase")
    active_agent = feedback_diagnostics.get("active_agent")
    replay_index = feedback_diagnostics.get("arm1_replay_index")
    replay_frame_count = feedback_diagnostics.get("arm1_timeline_frames")
    return {
        "status": str(diagnostics["message"]),
        "calibration_editor": (
            target.source_metadata.get("calibration_editor")
            if target_fresh and target is not None
            else (source_status or {}).get("source_metadata", {}).get("calibration_editor")
            if source_age_sec is not None and source_age_sec <= _SOURCE_STALE_SEC
            else None
        ),
        "severity": severity,
        "source": source_label,
        "quest": source_label,
        "controller": controller,
        "backend": backend,
        "view": view,
        "controller_position_m": position,
        "gate_open": bool(target_fresh and target is not None and target.gate_open),
        "recording": bool(feedback_fresh and feedback is not None and feedback.recording),
        "episode_id": feedback.episode_id if feedback_fresh and feedback is not None else None,
        "recording_phase": recording_phase if isinstance(recording_phase, str) else None,
        "active_agent": active_agent if isinstance(active_agent, str) else None,
        "replay_index": replay_index if isinstance(replay_index, int) else None,
        "replay_frame_count": (replay_frame_count if isinstance(replay_frame_count, int) else None),
    }


class CommandRouter:
    """Translate Foxglove services into acknowledged backend commands."""

    def __init__(
        self,
        request: Callable[[TeleopCommand], TeleopCommandResult],
    ) -> None:
        self.request = request

    def execute(self, command: str) -> dict[str, Any]:
        if command not in set(SERVICE_COMMANDS.values()):
            raise ValueError(f"unsupported teleop command: {command}")
        request = TeleopCommand(command=command, request_id=str(uuid.uuid4()))
        try:
            return self.request(request).to_dict()
        except (TimeoutError, RuntimeError, ValueError, zmq.ZMQError) as exc:
            return {
                "schema_version": "embodied.teleop_command_result/v1",
                "request_id": request.request_id,
                "command": request.command,
                "accepted": False,
                "applied": False,
                "backend": "",
                "message": str(exc),
                "duplicate": False,
                "completed_unix_ns": time.time_ns(),
            }

    def handler(self, command: str) -> Callable[[ServiceRequest], bytes]:
        def handle(_request: ServiceRequest) -> bytes:
            return json.dumps(self.execute(command), separators=(",", ":")).encode()

        return handle


def _json_message_schema(name: str, value: dict[str, Any]) -> MessageSchema:
    return MessageSchema(
        encoding="json",
        schema=Schema(
            name=name,
            encoding="jsonschema",
            data=json.dumps(value, separators=(",", ":")).encode(),
        ),
    )


def build_services(router: CommandRouter) -> list[Service]:
    empty = _json_message_schema(
        "embodied.teleop.EmptyRequest",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )
    response = _json_message_schema(
        "embodied.teleop.CommandResponse",
        {
            "type": "object",
            "properties": {
                "accepted": {"type": "boolean"},
                "applied": {"type": "boolean"},
                "command": {"type": "string"},
                "request_id": {"type": "string"},
                "backend": {"type": "string"},
                "message": {"type": "string"},
                "duplicate": {"type": "boolean"},
                "completed_unix_ns": {"type": "integer"},
            },
            "required": [
                "accepted",
                "applied",
                "command",
                "request_id",
                "backend",
                "message",
                "duplicate",
                "completed_unix_ns",
            ],
        },
    )
    schema = ServiceSchema("embodied.teleop.Command", request=empty, response=response)
    return [
        Service(name, schema=schema, handler=router.handler(command))
        for name, command in SERVICE_COMMANDS.items()
    ]


def calibration_service(endpoint: str) -> Service:
    schema = ServiceSchema(
        "embodied.teleop.SourceCalibration",
        request=_json_message_schema(
            "embodied.teleop.CalibrationRequest",
            {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                },
                "required": ["request_id"],
            },
        ),
        response=_json_message_schema(
            "embodied.teleop.CalibrationResponse",
            {
                "type": "object",
                "additionalProperties": True,
            },
        ),
    )

    def handle(request: ServiceRequest) -> bytes:
        try:
            data = json.loads(request.payload)
            payload = {"action": "begin", "request_id": data.get("request_id")}
            result = request_source_control(endpoint, json.dumps(payload).encode())
        except (ValueError, AttributeError) as exc:
            result = {"accepted": False, "applied": False, "message": str(exc)}
        return json.dumps(result).encode()

    return Service("/teleop/source/calibrate", schema=schema, handler=handle)


def feedback_telemetry(feedback: TeleopFeedback) -> dict[str, Any]:
    action = [float(item) for item in feedback.action[:7]]
    action.extend([None] * (7 - len(action)))
    position = [float(item) for item in feedback.eef_position[:3]]
    position.extend([0.0] * (3 - len(position)))
    wrench_fields = (
        "force_x_N",
        "force_y_N",
        "force_z_N",
        "force_norm_N",
        "torque_x_Nm",
        "torque_y_Nm",
        "torque_z_Nm",
        "torque_norm_Nm",
        "wrench_bias_ready",
    )
    return {
        "backend": feedback.backend,
        "episode_id": feedback.episode_id,
        "frame_index": feedback.frame_index,
        "status": feedback.status,
        "target_seq": feedback.target_seq,
        "target_age_ms": feedback.target_age_ms,
        "gate_open": feedback.gate_open,
        "recording": feedback.recording,
        "eef_x_m": position[0],
        "eef_y_m": position[1],
        "eef_z_m": position[2],
        "gripper": feedback.gripper,
        **{f"action_{index}": action[index] for index in range(7)},
        **{name: feedback.diagnostics.get(name) for name in wrench_fields},
        "diagnostics": feedback.diagnostics,
    }


def pose_message(
    *,
    timestamp_ns: int,
    frame_id: str,
    position: list[float],
    quaternion_xyzw: list[float],
) -> PoseInFrame:
    return PoseInFrame(
        timestamp=Timestamp(timestamp_ns // 1_000_000_000, timestamp_ns % 1_000_000_000),
        frame_id=frame_id,
        pose=Pose(
            position=Vector3(x=position[0], y=position[1], z=position[2]),
            orientation=Quaternion(
                x=quaternion_xyzw[0],
                y=quaternion_xyzw[1],
                z=quaternion_xyzw[2],
                w=quaternion_xyzw[3],
            ),
        ),
    )


def foxglove_deep_link(*, websocket_url: str, layout_id: str = "") -> str:
    """Build a Foxglove Web link for the live source and backend layout."""
    parameters = {
        "ds": "foxglove-websocket",
        "ds.url": websocket_url,
        "openIn": "web",
    }
    if layout_id:
        parameters["layoutId"] = layout_id
    return f"https://app.foxglove.dev/~/view?{urlencode(parameters)}"


def open_foxglove(deep_link: str) -> str:
    """Open the exact data source and layout in the default web browser."""

    subprocess.run(["open", deep_link], check=False)
    return "requested data source and layout"


class FoxgloveTeleopBridge:
    def __init__(
        self,
        *,
        target_endpoint: str,
        feedback_endpoint: str,
        command_endpoint: str,
        host: str,
        port: int,
        source_control_endpoint: str = DEFAULT_SOURCE_CONTROL_ENDPOINT,
    ) -> None:
        self.zmq_context = zmq.Context()
        self.target_socket = self.zmq_context.socket(zmq.SUB)
        self.target_socket.setsockopt(zmq.LINGER, 0)
        self.target_socket.setsockopt(zmq.RCVHWM, 4)
        self.target_socket.setsockopt(zmq.SUBSCRIBE, DEFAULT_TARGET_TOPIC)
        self.target_socket.setsockopt(zmq.SUBSCRIBE, DEFAULT_STATUS_TOPIC)
        self.target_socket.connect(target_endpoint)
        self.feedback = TeleopFeedbackReceiver(self.zmq_context, feedback_endpoint)
        self.command = TeleopCommandClient(
            self.zmq_context,
            command_endpoint,
        )
        self.poller = zmq.Poller()
        self.poller.register(self.target_socket, zmq.POLLIN)
        self.poller.register(self.feedback.socket, zmq.POLLIN)

        self.router = CommandRouter(
            lambda command: self.command.request(
                command,
                timeout_ms=COMMAND_TIMEOUT_MS.get(command.command, 5_000),
            )
        )
        self.foxglove_context = foxglove.Context()
        self.agent_channel = CompressedImageChannel(
            "/teleop/agent_view", context=self.foxglove_context
        )
        self.wrist_channel = CompressedImageChannel(
            "/teleop/wrist_camera", context=self.foxglove_context
        )
        self.eef_pose_channel = PoseInFrameChannel(
            "/teleop/eef_pose", context=self.foxglove_context
        )
        self.desired_eef_pose_channel = PoseInFrameChannel(
            "/teleop/desired_eef_pose", context=self.foxglove_context
        )
        self.target_pose_channel = PoseInFrameChannel(
            "/teleop/controller_target", context=self.foxglove_context
        )
        self.controller_scene = ControllerScene()
        self.controller_scene_channel = SceneUpdateChannel(
            "/teleop/controller_scene", context=self.foxglove_context
        )
        self.last_scene_at = 0.0
        self.telemetry_channel = foxglove.Channel(
            "/teleop/telemetry",
            schema=TELEMETRY_SCHEMA,
            message_encoding="json",
            context=self.foxglove_context,
        )
        self.target_channel = foxglove.Channel(
            "/teleop/target",
            schema={"type": "object", "additionalProperties": True},
            message_encoding="json",
            context=self.foxglove_context,
        )
        self.tracker_channel = foxglove.Channel(
            "/teleop/source_status",
            schema={"type": "object", "additionalProperties": True},
            message_encoding="json",
            context=self.foxglove_context,
        )
        self.diagnostics_channel = foxglove.Channel(
            "/teleop/diagnostics",
            schema=Schema(
                name="diagnostic_msgs/msg/DiagnosticArray",
                encoding="jsonschema",
                data=json.dumps(DIAGNOSTIC_ARRAY_SCHEMA, separators=(",", ":")).encode(),
            ),
            message_encoding="json",
            context=self.foxglove_context,
        )
        self.operator_state_channel = foxglove.Channel(
            "/teleop/operator_state",
            schema=OPERATOR_STATE_SCHEMA,
            message_encoding="json",
            context=self.foxglove_context,
        )
        self.server = foxglove.start_server(
            name="Embodied teleoperation",
            host=host,
            port=port,
            capabilities=[Capability.Services],
            services=[*build_services(self.router), calibration_service(source_control_endpoint)],
            context=self.foxglove_context,
            message_backlog_size=4,
        )
        self.forwarded_feedback = 0
        self.forwarded_targets = 0
        self.latest_source_status: dict[str, Any] | None = None
        self.latest_source_at: float | None = None
        self.latest_target: TeleopTarget | None = None
        self.latest_target_at: float | None = None
        self.latest_feedback: TeleopFeedback | None = None
        self.latest_feedback_at: float | None = None
        self.last_diagnostics_at = 0.0

    @property
    def port(self) -> int:
        return int(self.server.port)

    def poll(self, timeout_ms: int) -> None:
        ready = dict(self.poller.poll(timeout_ms))
        if self.target_socket in ready:
            self._take_targets()
        if self.feedback.socket in ready:
            latest = self.feedback.newest()
            if latest is not None:
                self._publish_feedback(*latest)
        self._publish_diagnostics_if_due()
        now = time.monotonic()
        if self.latest_target_at is None or now - self.latest_target_at > 0.5:
            self.controller_scene.disconnect()
        if now - self.last_scene_at >= 0.1:
            timestamp_ns = time.time_ns()
            self.controller_scene_channel.log(
                self.controller_scene.message(timestamp_ns), log_time=timestamp_ns
            )
            self.last_scene_at = now

    def _take_targets(self) -> None:
        while True:
            try:
                topic, payload = self.target_socket.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                return
            timestamp_ns = time.time_ns()
            if topic == DEFAULT_STATUS_TOPIC:
                try:
                    status = TeleopSourceStatus.from_json(payload)
                except (KeyError, UnicodeDecodeError, ValueError):
                    continue
                value = status.to_dict()
                self.latest_source_status = value
                self.latest_source_at = time.monotonic()
                if not status.tracking_valid or not status.stream_online:
                    self.controller_scene.disconnect()
                elif not status.gate_open:
                    self.controller_scene.break_trail = True
                self.tracker_channel.log(value, log_time=timestamp_ns)
            elif topic == DEFAULT_TARGET_TOPIC:
                try:
                    target = TeleopTarget.from_json(payload)
                except (KeyError, UnicodeDecodeError, ValueError):
                    continue
                self.latest_target = target
                self.controller_scene.observe(target)
                self.latest_target_at = time.monotonic()
                timestamp_ns = target.host_published_unix_ns or timestamp_ns
                self.target_channel.log(target.to_dict(), log_time=timestamp_ns)
                self.target_pose_channel.log(
                    pose_message(
                        timestamp_ns=timestamp_ns,
                        frame_id="teleop_world",
                        position=target.position,
                        quaternion_xyzw=matrix_to_quat_xyzw(target.rotation),
                    ),
                    log_time=timestamp_ns,
                )
                self.forwarded_targets += 1

    def _publish_feedback(
        self, feedback: TeleopFeedback, agent_jpeg: bytes, wrist_jpeg: bytes
    ) -> None:
        previous = self.latest_feedback
        if previous is not None and (
            previous.episode_id != feedback.episode_id
            or feedback.frame_index < previous.frame_index
        ):
            self.controller_scene.reset()
        self.latest_feedback = feedback
        self.latest_feedback_at = time.monotonic()
        timestamp_ns = feedback.timestamp_unix_ns
        self.agent_channel.log(
            CompressedImage(
                timestamp=Timestamp(
                    timestamp_ns // 1_000_000_000,
                    timestamp_ns % 1_000_000_000,
                ),
                frame_id=f"{feedback.backend}/agent_camera",
                data=agent_jpeg,
                format="jpeg",
            ),
            log_time=timestamp_ns,
        )
        self.wrist_channel.log(
            CompressedImage(
                timestamp=Timestamp(
                    timestamp_ns // 1_000_000_000,
                    timestamp_ns % 1_000_000_000,
                ),
                frame_id=f"{feedback.backend}/wrist_camera",
                data=wrist_jpeg,
                format="jpeg",
            ),
            log_time=timestamp_ns,
        )
        orientation = feedback.eef_orientation_xyzw or [0.0, 0.0, 0.0, 1.0]
        self.eef_pose_channel.log(
            pose_message(
                timestamp_ns=timestamp_ns,
                frame_id="teleop_world",
                position=feedback.eef_position,
                quaternion_xyzw=orientation,
            ),
            log_time=timestamp_ns,
        )
        if feedback.desired_eef_position is not None:
            desired_orientation = feedback.desired_eef_orientation_xyzw or orientation
            self.desired_eef_pose_channel.log(
                pose_message(
                    timestamp_ns=timestamp_ns,
                    frame_id="teleop_world",
                    position=feedback.desired_eef_position,
                    quaternion_xyzw=desired_orientation,
                ),
                log_time=timestamp_ns,
            )
        self.telemetry_channel.log(feedback_telemetry(feedback), log_time=timestamp_ns)
        self.forwarded_feedback += 1

    def _publish_diagnostics_if_due(self) -> None:
        now = time.monotonic()
        if now - self.last_diagnostics_at < 0.2:
            return
        timestamp_ns = time.time_ns()
        state_inputs = {
            "timestamp_ns": timestamp_ns,
            "source_status": self.latest_source_status,
            "source_age_sec": (
                None if self.latest_source_at is None else max(0.0, now - self.latest_source_at)
            ),
            "target": self.latest_target,
            "target_age_sec": (
                None if self.latest_target_at is None else max(0.0, now - self.latest_target_at)
            ),
            "feedback": self.latest_feedback,
            "feedback_age_sec": (
                None if self.latest_feedback_at is None else max(0.0, now - self.latest_feedback_at)
            ),
        }
        value = diagnostic_array(
            **state_inputs,
        )
        self.diagnostics_channel.log(value, log_time=timestamp_ns)
        self.operator_state_channel.log(operator_state(**state_inputs), log_time=timestamp_ns)
        self.last_diagnostics_at = now

    def close(self) -> None:
        self.server.stop()
        self.poller.unregister(self.target_socket)
        self.poller.unregister(self.feedback.socket)
        self.target_socket.close(0)
        self.feedback.close()
        self.command.close()
        self.zmq_context.term()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-endpoint", default=DEFAULT_TARGET_ENDPOINT)
    parser.add_argument("--feedback-endpoint", default=DEFAULT_FEEDBACK_ENDPOINT)
    parser.add_argument("--command-endpoint", default=DEFAULT_COMMAND_ENDPOINT)
    parser.add_argument("--source-control-endpoint", default=DEFAULT_SOURCE_CONTROL_ENDPOINT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-foxglove", action="store_true")
    parser.add_argument(
        "--layout-id",
        default=DEFAULT_FOXGLOVE_LAYOUT_ID,
        help="Remote Foxglove layout ID to select; pass an empty string to omit it.",
    )
    parser.add_argument("--duration-sec", type=float, default=0.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise ValueError("--port must be from 1 to 65535")
    if args.duration_sec < 0:
        raise ValueError("--duration-sec must be non-negative")
    bridge = FoxgloveTeleopBridge(
        target_endpoint=args.target_endpoint,
        feedback_endpoint=args.feedback_endpoint,
        command_endpoint=args.command_endpoint,
        source_control_endpoint=args.source_control_endpoint,
        host=args.host,
        port=args.port,
    )
    stop = False

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    url = f"ws://{args.host}:{bridge.port}"
    print(f"Foxglove teleop gateway: {url}", flush=True)
    if args.open_foxglove:
        deep_link = foxglove_deep_link(
            websocket_url=url,
            layout_id=args.layout_id,
        )
        opened = open_foxglove(deep_link)
        print(f"Foxglove UI: activated {opened}.", flush=True)
    started = time.monotonic()
    try:
        while not stop and (
            args.duration_sec <= 0 or time.monotonic() - started < args.duration_sec
        ):
            bridge.poll(50)
    finally:
        print(
            f"Foxglove bridge stopped: targets={bridge.forwarded_targets} "
            f"feedback={bridge.forwarded_feedback}",
            flush=True,
        )
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
