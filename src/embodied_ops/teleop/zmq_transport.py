"""Optional ZeroMQ data plane for the hardware-independent teleop contracts."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

try:
    import zmq
except ImportError as exc:  # pragma: no cover - exercised by minimal installs
    raise ImportError(
        "embodied_ops.teleop.zmq_transport requires embodied-ops[teleop-zmq]"
    ) from exc

from .contracts import (
    TeleopCommand,
    TeleopCommandResult,
    TeleopFeedback,
    TeleopTarget,
)

DEFAULT_TARGET_ENDPOINT = "tcp://127.0.0.1:8130"
DEFAULT_FEEDBACK_ENDPOINT = "tcp://127.0.0.1:8131"
DEFAULT_COMMAND_ENDPOINT = "tcp://127.0.0.1:8132"

DEFAULT_TARGET_TOPIC = b"teleop_target"
DEFAULT_STATUS_TOPIC = b"teleop_status"
DEFAULT_FEEDBACK_TOPIC = b"teleop_feedback"
DEFAULT_COMMAND_TOPIC = b"teleop_command"
DEFAULT_COMMAND_RESULT_TOPIC = b"teleop_command_result"


class TeleopTargetPublisher:
    """Non-blocking PUB socket for calibrated source-neutral targets."""

    def __init__(
        self,
        context: zmq.Context,
        endpoint: str = DEFAULT_TARGET_ENDPOINT,
        *,
        bind: bool = True,
    ) -> None:
        self.socket = context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.SNDHWM, 1)
        (self.socket.bind if bind else self.socket.connect)(endpoint)
        self.dropped = 0

    def publish(self, target: TeleopTarget) -> bool:
        try:
            self.socket.send_multipart(
                [DEFAULT_TARGET_TOPIC, target.to_json().encode("utf-8")],
                flags=zmq.NOBLOCK,
            )
        except zmq.Again:
            self.dropped += 1
            return False
        return True

    def publish_status(self, payload: bytes) -> bool:
        try:
            self.socket.send_multipart(
                [DEFAULT_STATUS_TOPIC, bytes(payload)],
                flags=zmq.NOBLOCK,
            )
        except zmq.Again:
            self.dropped += 1
            return False
        return True

    def close(self) -> None:
        self.socket.close(0)


class TeleopTargetSubscriber:
    """SUB client that drains queued frames and returns only the newest target."""

    def __init__(
        self,
        context: zmq.Context,
        endpoint: str = DEFAULT_TARGET_ENDPOINT,
    ) -> None:
        self.socket = context.socket(zmq.SUB)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.RCVHWM, 4)
        self.socket.setsockopt(zmq.SUBSCRIBE, DEFAULT_TARGET_TOPIC)
        self.socket.connect(endpoint)

    def poll(self, timeout_ms: int = 0) -> TeleopTarget | None:
        if timeout_ms > 0 and not self.socket.poll(timeout_ms, zmq.POLLIN):
            return None
        latest = None
        while True:
            try:
                topic, payload = self.socket.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                return latest
            if topic == DEFAULT_TARGET_TOPIC:
                latest = TeleopTarget.from_json(payload)

    def close(self) -> None:
        self.socket.close(0)


class TeleopFeedbackPublisher:
    """Non-blocking PUB server used by the one active simulator backend."""

    def __init__(
        self,
        context: zmq.Context,
        endpoint: str = DEFAULT_FEEDBACK_ENDPOINT,
    ) -> None:
        self.socket = context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.SNDHWM, 1)
        self.socket.bind(endpoint)
        self.dropped = 0

    def publish(
        self,
        feedback: TeleopFeedback,
        agent_view_jpeg: bytes,
        wrist_jpeg: bytes,
    ) -> bool:
        try:
            self.socket.send_multipart(
                [
                    DEFAULT_FEEDBACK_TOPIC,
                    feedback.to_json(),
                    bytes(agent_view_jpeg),
                    bytes(wrist_jpeg),
                ],
                flags=zmq.NOBLOCK,
            )
        except zmq.Again:
            self.dropped += 1
            return False
        return True

    def close(self) -> None:
        self.socket.close(0)


class TeleopFeedbackReceiver:
    """Subscribe to feedback and retain only the newest complete sample."""

    def __init__(
        self,
        context: zmq.Context,
        endpoint: str = DEFAULT_FEEDBACK_ENDPOINT,
    ) -> None:
        self.socket = context.socket(zmq.SUB)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.RCVHWM, 4)
        self.socket.setsockopt(zmq.SUBSCRIBE, DEFAULT_FEEDBACK_TOPIC)
        self.socket.connect(endpoint)

    def newest(self) -> tuple[TeleopFeedback, bytes, bytes] | None:
        latest = None
        while True:
            try:
                parts = self.socket.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                return latest
            if len(parts) != 4 or parts[0] != DEFAULT_FEEDBACK_TOPIC:
                continue
            latest = (TeleopFeedback.from_json(parts[1]), parts[2], parts[3])

    def close(self) -> None:
        self.socket.close(0)


@dataclass(frozen=True, slots=True)
class TeleopCommandRequest:
    routing_id: bytes
    command: TeleopCommand


class TeleopCommandClient:
    """DEALER client that receives a backend acknowledgement for every request."""

    def __init__(
        self,
        context: zmq.Context,
        endpoint: str = DEFAULT_COMMAND_ENDPOINT,
        *,
        identity: str | None = None,
    ) -> None:
        self.socket = context.socket(zmq.DEALER)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.SNDHWM, 8)
        self.socket.setsockopt(zmq.RCVHWM, 8)
        self.socket.setsockopt(
            zmq.IDENTITY,
            (identity or f"teleop-ui-{uuid.uuid4()}").encode("utf-8"),
        )
        self.socket.connect(endpoint)
        self._lock = threading.Lock()

    def send(self, command: TeleopCommand) -> None:
        self.socket.send_multipart([DEFAULT_COMMAND_TOPIC, command.to_json()])

    def receive(self, timeout_ms: int = 1000) -> TeleopCommandResult:
        if not self.socket.poll(timeout_ms, zmq.POLLIN):
            raise TimeoutError("teleop backend did not acknowledge the command")
        topic, payload = self.socket.recv_multipart()
        if topic != DEFAULT_COMMAND_RESULT_TOPIC:
            raise RuntimeError("teleop backend returned an unexpected message")
        return TeleopCommandResult.from_json(payload)

    def request(
        self,
        command: TeleopCommand,
        *,
        timeout_ms: int = 1000,
    ) -> TeleopCommandResult:
        with self._lock:
            self.send(command)
            deadline = time.monotonic() + timeout_ms / 1000.0
            while True:
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                result = self.receive(remaining_ms)
                if result.request_id == command.request_id:
                    return result

    def close(self) -> None:
        self.socket.close(0)


class TeleopCommandServer:
    """ROUTER server with bounded idempotent command-result replay."""

    def __init__(
        self,
        context: zmq.Context,
        endpoint: str = DEFAULT_COMMAND_ENDPOINT,
        *,
        result_cache_size: int = 256,
    ) -> None:
        if result_cache_size <= 0:
            raise ValueError("result_cache_size must be positive")
        self.socket = context.socket(zmq.ROUTER)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.SNDHWM, 8)
        self.socket.setsockopt(zmq.RCVHWM, 8)
        self.socket.bind(endpoint)
        self.result_cache_size = result_cache_size
        self._results: OrderedDict[str, bytes] = OrderedDict()
        self.invalid_requests = 0

    def take_all(self) -> list[TeleopCommandRequest]:
        requests = []
        while True:
            try:
                parts = self.socket.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                return requests
            if len(parts) != 3:
                self.invalid_requests += 1
                continue
            routing_id, topic, payload = parts
            if topic != DEFAULT_COMMAND_TOPIC:
                continue
            try:
                command = TeleopCommand.from_json(payload)
            except (UnicodeDecodeError, ValueError):
                self.invalid_requests += 1
                continue
            cached = self._results.get(command.request_id)
            if cached is not None:
                duplicate = TeleopCommandResult.from_json(cached)
                replay = TeleopCommandResult(
                    request_id=duplicate.request_id,
                    command=duplicate.command,
                    accepted=duplicate.accepted,
                    applied=duplicate.applied,
                    backend=duplicate.backend,
                    message=duplicate.message,
                    duplicate=True,
                    completed_unix_ns=duplicate.completed_unix_ns,
                )
                self.socket.send_multipart(
                    [routing_id, DEFAULT_COMMAND_RESULT_TOPIC, replay.to_json()]
                )
                continue
            requests.append(TeleopCommandRequest(routing_id, command))

    def reply(
        self,
        request: TeleopCommandRequest,
        *,
        backend: str,
        accepted: bool,
        applied: bool,
        message: str = "",
    ) -> TeleopCommandResult:
        result = TeleopCommandResult(
            request_id=request.command.request_id,
            command=request.command.command,
            accepted=accepted,
            applied=applied,
            backend=backend,
            message=message,
        )
        encoded = result.to_json()
        self._results[result.request_id] = encoded
        self._results.move_to_end(result.request_id)
        while len(self._results) > self.result_cache_size:
            self._results.popitem(last=False)
        self.socket.send_multipart([request.routing_id, DEFAULT_COMMAND_RESULT_TOPIC, encoded])
        return result

    def close(self) -> None:
        self.socket.close(0)
