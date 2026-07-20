"""Remote OperationalDevice client for the versioned gRPC contract."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import grpc

from embodied_ops import __version__
from embodied_ops.device import Capability, DeviceManifest, HealthReport, HealthStatus
from embodied_ops.endpoints import unix_socket_path
from embodied_ops.errors import ContractError, LifecycleError, RpcError
from embodied_ops.features import validate_feature_values
from embodied_ops.rpc._codec import (
    health_from_proto,
    manifest_from_proto,
    values_from_proto,
    values_to_proto,
)
from embodied_ops.rpc.types import PROTOCOL_VERSION, SessionMode
from embodied_ops.rpc.v1 import device_pb2, device_pb2_grpc


class RemoteDevice:
    """Thin client; the server process remains the sole device and hardware owner."""

    def __init__(
        self,
        *,
        endpoint: str,
        mode: SessionMode = SessionMode.COMMAND,
        client_name: str = "embodied-ops-python",
        connect_timeout_s: float = 5.0,
        rpc_timeout_s: float = 2.0,
    ) -> None:
        unix_socket_path(endpoint)
        _validate_positive_timeout("connect_timeout_s", connect_timeout_s)
        _validate_positive_timeout("rpc_timeout_s", rpc_timeout_s)
        _validate_client_identity(client_name)
        if not isinstance(mode, SessionMode):
            raise ContractError(f"unsupported session mode: {mode!r}")
        self.endpoint = endpoint
        self.mode = mode
        self.client_name = client_name
        self.connect_timeout_s = float(connect_timeout_s)
        self.rpc_timeout_s = float(rpc_timeout_s)
        self._channel: grpc.Channel | None = None
        self._stub: device_pb2_grpc.DeviceServiceStub | None = None
        self._manifest: DeviceManifest | None = None
        self._session_id: str | None = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._fatal_error: RpcError | None = None
        self._command_lock = threading.Lock()
        self._next_command_sequence = 1
        self._last_command_timestamp_ns = 0

    @property
    def manifest(self) -> DeviceManifest:
        if self._manifest is None:
            response = self._call(
                lambda stub: stub.Describe(
                    device_pb2.DescribeRequest(protocol_version=PROTOCOL_VERSION),
                    timeout=self.connect_timeout_s,
                ),
                operation="describe",
            )
            if response.protocol_version != PROTOCOL_VERSION:
                raise RpcError(
                    f"server selected protocol {response.protocol_version}; "
                    f"expected {PROTOCOL_VERSION}"
                )
            self._manifest = manifest_from_proto(response.manifest)
        return self._manifest

    @property
    def is_connected(self) -> bool:
        return self._session_id is not None and self._fatal_error is None

    @property
    def is_calibrated(self) -> bool:
        if Capability.CALIBRATE not in self.manifest.capabilities:
            return True
        session_id = self._require_session()
        response = self._call(
            lambda stub: stub.CalibrationState(
                device_pb2.SessionRequest(session_id=session_id),
                timeout=self.rpc_timeout_s,
            ),
            operation="read calibration state",
        )
        return response.is_calibrated

    def connect(self) -> None:
        if self._session_id is not None:
            raise LifecycleError("remote device is already connected")
        manifest = self.manifest
        requested_capability = (
            Capability.OBSERVE if self.mode is SessionMode.OBSERVE else Capability.COMMAND
        )
        if requested_capability not in manifest.capabilities:
            raise LifecycleError(f"remote device does not expose {requested_capability.value}")
        response = self._call(
            lambda stub: stub.Open(
                device_pb2.OpenRequest(
                    protocol_version=PROTOCOL_VERSION,
                    mode=_session_mode_to_proto(self.mode),
                    client_name=self.client_name,
                    client_version=__version__,
                ),
                timeout=self.connect_timeout_s,
            ),
            operation="connect",
        )
        opened_manifest = manifest_from_proto(response.manifest)
        if opened_manifest != manifest:
            self._best_effort_close(response.session_id)
            raise RpcError("device manifest changed during session establishment")
        if response.lease_timeout_ms <= 0:
            self._best_effort_close(response.session_id)
            raise RpcError("server returned an invalid session lease")
        if self.mode is SessionMode.COMMAND and (
            response.command_timeout_ms <= 0
            or response.command_timeout_ms > response.lease_timeout_ms
        ):
            self._best_effort_close(response.session_id)
            raise RpcError("server returned an invalid command inactivity timeout")
        self._session_id = response.session_id
        self._fatal_error = None
        self._next_command_sequence = 1
        self._last_command_timestamp_ns = 0
        self._start_heartbeat(response.lease_timeout_ms / 1000)

    def observe(self) -> Mapping[str, object]:
        session_id = self._require_session()
        if Capability.OBSERVE not in self.manifest.capabilities:
            raise LifecycleError("remote device is not observable")
        response = self._call(
            lambda stub: stub.Observe(
                device_pb2.SessionRequest(session_id=session_id),
                timeout=self.rpc_timeout_s,
            ),
            operation="observe",
        )
        return values_from_proto(response.values, self.manifest.observation_features)

    def command(self, action: Mapping[str, object]) -> Mapping[str, object]:
        if self.mode is not SessionMode.COMMAND:
            raise LifecycleError("remote session does not own command access")
        session_id = self._require_session()
        requested = validate_feature_values(action, self.manifest.action_features)
        with self._command_lock:
            timestamp_ns = max(time.monotonic_ns(), self._last_command_timestamp_ns + 1)
            sequence = self._next_command_sequence
            try:
                response = self._call(
                    lambda stub: stub.Command(
                        device_pb2.CommandRequest(
                            session_id=session_id,
                            sequence=sequence,
                            sent_monotonic_ns=timestamp_ns,
                            values=values_to_proto(requested, self.manifest.action_features),
                        ),
                        timeout=self.rpc_timeout_s,
                    ),
                    operation="command",
                )
            except RpcError as exc:
                self._fatal_error = exc
                self._heartbeat_stop.set()
                raise
            self._next_command_sequence += 1
            self._last_command_timestamp_ns = timestamp_ns
        return values_from_proto(response.values, self.manifest.action_features)

    def health(self) -> HealthReport:
        if self._session_id is None:
            return HealthReport(HealthStatus.UNKNOWN, "remote device is disconnected")
        session_id = self._require_session()
        response = self._call(
            lambda stub: stub.Health(
                device_pb2.SessionRequest(session_id=session_id),
                timeout=self.rpc_timeout_s,
            ),
            operation="health",
        )
        return health_from_proto(response)

    def calibrate(self) -> None:
        if Capability.CALIBRATE not in self.manifest.capabilities:
            raise LifecycleError("remote device is not calibratable")
        session_id = self._require_session()
        self._call(
            lambda stub: stub.Calibrate(
                device_pb2.SessionRequest(session_id=session_id),
                timeout=self.rpc_timeout_s,
            ),
            operation="calibrate",
        )

    def reset(self, target: str | None = None) -> None:
        if Capability.RESET not in self.manifest.capabilities:
            raise LifecycleError("remote device is not resettable")
        session_id = self._require_session()
        request = device_pb2.ResetRequest(session_id=session_id)
        if target is not None:
            request.target = target
        self._call(
            lambda stub: stub.Reset(request, timeout=self.rpc_timeout_s),
            operation="reset",
        )

    def disconnect(self) -> None:
        session_id, self._session_id = self._session_id, None
        self._stop_heartbeat()
        error: RpcError | None = None
        if session_id is not None:
            try:
                self._best_effort_close(session_id, suppress_errors=False)
            except RpcError as exc:
                error = exc
        self._fatal_error = None
        if self._channel is not None:
            self._channel.close()
        self._channel = None
        self._stub = None
        if error is not None:
            raise error

    def _require_session(self) -> str:
        if self._fatal_error is not None:
            raise LifecycleError(f"remote session failed: {self._fatal_error}")
        if self._session_id is None:
            raise LifecycleError("remote device is not connected")
        return self._session_id

    def _call(self, call: Callable[[Any], Any], *, operation: str) -> Any:
        stub = self._ensure_stub()
        try:
            return call(stub)
        except grpc.RpcError as exc:
            code = exc.code().name if exc.code() is not None else "UNKNOWN"
            details = exc.details() or "no server details"
            raise RpcError(f"RPC {operation} failed [{code}]: {details}") from exc

    def _ensure_stub(self) -> device_pb2_grpc.DeviceServiceStub:
        if self._stub is None:
            self._channel = grpc.insecure_channel(self.endpoint)
            self._stub = device_pb2_grpc.DeviceServiceStub(self._channel)
        return self._stub

    def _start_heartbeat(self, lease_timeout_s: float) -> None:
        self._heartbeat_stop.clear()
        interval_s = lease_timeout_s / 3
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(interval_s,),
            name="embodied-ops-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self, interval_s: float) -> None:
        while not self._heartbeat_stop.wait(interval_s):
            session_id = self._session_id
            if session_id is None:
                return
            try:
                self._call(
                    lambda stub, session_id=session_id: stub.Heartbeat(
                        device_pb2.SessionRequest(session_id=session_id),
                        timeout=min(self.rpc_timeout_s, interval_s),
                    ),
                    operation="heartbeat",
                )
            except RpcError as exc:
                if not self._heartbeat_stop.is_set():
                    self._fatal_error = exc
                return

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=self.rpc_timeout_s + 0.5)
        self._heartbeat_thread = None

    def _best_effort_close(self, session_id: str, *, suppress_errors: bool = True) -> None:
        try:
            self._call(
                lambda stub: stub.Close(
                    device_pb2.SessionRequest(session_id=session_id),
                    timeout=self.rpc_timeout_s,
                ),
                operation="disconnect",
            )
        except RpcError:
            if not suppress_errors:
                raise


def _validate_positive_timeout(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _validate_client_identity(value: str) -> None:
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise ContractError(f"invalid RPC client name: {value!r}")


def _session_mode_to_proto(mode: SessionMode) -> int:
    if mode is SessionMode.OBSERVE:
        return device_pb2.SESSION_MODE_OBSERVE
    if mode is SessionMode.COMMAND:
        return device_pb2.SESSION_MODE_COMMAND
    raise ContractError(f"unsupported session mode: {mode!r}")
