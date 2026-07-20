"""Fail-closed gRPC server for one operational device."""

from __future__ import annotations

import math
import os
import stat
import threading
import time
import uuid
from concurrent import futures
from dataclasses import dataclass

import grpc
from google.protobuf.empty_pb2 import Empty

from embodied_ops.device import (
    CalibratableDevice,
    Capability,
    CommandDevice,
    CommandLeaseDevice,
    ObservableDevice,
    OperationalDevice,
    ResettableDevice,
)
from embodied_ops.errors import ContractError, LifecycleError
from embodied_ops.endpoints import unix_socket_path
from embodied_ops.rpc._codec import (
    health_to_proto,
    manifest_to_proto,
    values_from_proto,
    values_to_proto,
)
from embodied_ops.rpc.types import PROTOCOL_VERSION, SessionMode
from embodied_ops.rpc.v1 import device_pb2, device_pb2_grpc


@dataclass(slots=True)
class _Session:
    mode: SessionMode
    last_seen: float
    last_command: float | None = None
    last_command_sequence: int = 0
    last_command_timestamp_ns: int = 0


class _DeviceService(device_pb2_grpc.DeviceServiceServicer):
    def __init__(
        self,
        device: OperationalDevice,
        *,
        lease_timeout_s: float,
        command_timeout_s: float,
        monotonic=time.monotonic,
    ) -> None:
        self.device = device
        self.lease_timeout_s = lease_timeout_s
        self.command_timeout_s = command_timeout_s
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._sessions: dict[str, _Session] = {}
        self._command_session_id: str | None = None
        self._closed = False

    def Describe(self, request, context):
        self._require_protocol(request.protocol_version, context)
        return device_pb2.DescribeResponse(
            protocol_version=PROTOCOL_VERSION,
            manifest=manifest_to_proto(self.device.manifest),
        )

    def Open(self, request, context):
        self._require_protocol(request.protocol_version, context)
        try:
            mode = _session_mode_from_proto(request.mode)
            _validate_client_identity(request.client_name, request.client_version)
            with self._lock:
                if self._closed:
                    raise LifecycleError("device RPC service is stopping")
                self._expire_sessions_locked()
                self._require_mode_capability(mode)
                if mode is SessionMode.COMMAND and self._command_session_id is not None:
                    raise _CommandLeaseUnavailable("a command session already owns this device")
                connected_here = not self.device.is_connected
                if connected_here:
                    self.device.connect()
                try:
                    if mode is SessionMode.COMMAND and isinstance(self.device, CommandLeaseDevice):
                        self.device.acquire_command_lease()
                except Exception:
                    if connected_here and not self._sessions:
                        self._disconnect_device_locked()
                    raise
                session_id = uuid.uuid4().hex
                opened_at = self._monotonic()
                self._sessions[session_id] = _Session(
                    mode,
                    opened_at,
                    last_command=opened_at if mode is SessionMode.COMMAND else None,
                )
                if mode is SessionMode.COMMAND:
                    self._command_session_id = session_id
                return device_pb2.OpenResponse(
                    session_id=session_id,
                    lease_timeout_ms=round(self.lease_timeout_s * 1000),
                    manifest=manifest_to_proto(self.device.manifest),
                    command_timeout_ms=round(self.command_timeout_s * 1000),
                )
        except _CommandLeaseUnavailable as exc:
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, str(exc))
        except (ContractError, LifecycleError, ValueError) as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception as exc:
            context.abort(grpc.StatusCode.INTERNAL, f"device connect failed: {exc}")

    def Heartbeat(self, request, context):
        try:
            with self._lock:
                self._require_session_locked(request.session_id)
            return Empty()
        except LifecycleError as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))

    def Observe(self, request, context):
        try:
            with self._lock:
                self._require_session_locked(request.session_id)
                if Capability.OBSERVE not in self.device.manifest.capabilities:
                    raise LifecycleError("device does not expose the observe capability")
                if not isinstance(self.device, ObservableDevice):
                    raise LifecycleError("device violates its observe capability")
                values = self.device.observe()
                return device_pb2.ValuesResponse(
                    values=values_to_proto(values, self.device.manifest.observation_features)
                )
        except (ContractError, LifecycleError) as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception as exc:
            context.abort(grpc.StatusCode.INTERNAL, f"device observation failed: {exc}")

    def Command(self, request, context):
        try:
            with self._lock:
                session = self._require_session_locked(request.session_id)
                if session.mode is not SessionMode.COMMAND:
                    raise LifecycleError("session does not own command access")
                if request.sequence != session.last_command_sequence + 1:
                    raise LifecycleError(
                        "command sequence must be contiguous and strictly increasing"
                    )
                if (
                    request.sent_monotonic_ns <= 0
                    or request.sent_monotonic_ns <= session.last_command_timestamp_ns
                ):
                    raise LifecycleError(
                        "command timestamp must be positive and strictly increasing"
                    )
                if not isinstance(self.device, CommandDevice):
                    raise LifecycleError("device violates its command capability")
                action = values_from_proto(request.values, self.device.manifest.action_features)
                try:
                    accepted = self.device.command(action)
                    response = device_pb2.ValuesResponse(
                        values=values_to_proto(accepted, self.device.manifest.action_features)
                    )
                except Exception:
                    self._close_command_session_locked()
                    raise
                session.last_command_sequence = request.sequence
                session.last_command_timestamp_ns = request.sent_monotonic_ns
                session.last_command = self._monotonic()
                return response
        except (ContractError, LifecycleError) as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception as exc:
            context.abort(
                grpc.StatusCode.INTERNAL,
                f"device command failed and the session was closed: {exc}",
            )

    def Health(self, request, context):
        try:
            with self._lock:
                self._require_session_locked(request.session_id)
                return health_to_proto(self.device.health())
        except (ContractError, LifecycleError) as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception as exc:
            context.abort(grpc.StatusCode.INTERNAL, f"device health check failed: {exc}")

    def CalibrationState(self, request, context):
        try:
            with self._lock:
                self._require_session_locked(request.session_id)
                if Capability.CALIBRATE not in self.device.manifest.capabilities:
                    return device_pb2.CalibrationStateResponse(is_calibrated=True)
                if not isinstance(self.device, CalibratableDevice):
                    raise LifecycleError("device violates its calibrate capability")
                return device_pb2.CalibrationStateResponse(is_calibrated=self.device.is_calibrated)
        except LifecycleError as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))

    def Calibrate(self, request, context):
        try:
            with self._lock:
                session = self._require_command_session_locked(request.session_id)
                if Capability.CALIBRATE not in self.device.manifest.capabilities:
                    raise LifecycleError("device does not expose the calibrate capability")
                if not isinstance(self.device, CalibratableDevice):
                    raise LifecycleError("device violates its calibrate capability")
                try:
                    self.device.calibrate()
                except Exception:
                    self._close_command_session_locked()
                    raise
                session.last_command = self._monotonic()
            return Empty()
        except LifecycleError as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception as exc:
            context.abort(
                grpc.StatusCode.INTERNAL,
                f"device calibration failed and the session was closed: {exc}",
            )

    def Reset(self, request, context):
        try:
            with self._lock:
                session = self._require_command_session_locked(request.session_id)
                if Capability.RESET not in self.device.manifest.capabilities:
                    raise LifecycleError("device does not expose the reset capability")
                if not isinstance(self.device, ResettableDevice):
                    raise LifecycleError("device violates its reset capability")
                target = request.target if request.HasField("target") else None
                try:
                    self.device.reset(target)
                except Exception:
                    self._close_command_session_locked()
                    raise
                session.last_command = self._monotonic()
            return Empty()
        except LifecycleError as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception as exc:
            context.abort(
                grpc.StatusCode.INTERNAL,
                f"device reset failed and the session was closed: {exc}",
            )

    def Close(self, request, context):
        try:
            with self._lock:
                session = self._sessions.get(request.session_id)
                if session is None:
                    return Empty()
                if session.mode is SessionMode.COMMAND:
                    self._close_command_session_locked()
                else:
                    del self._sessions[request.session_id]
                    if not self._sessions:
                        self._disconnect_device_locked()
            return Empty()
        except Exception as exc:
            context.abort(grpc.StatusCode.INTERNAL, f"device disconnect failed: {exc}")

    def expire_sessions(self) -> None:
        with self._lock:
            self._expire_sessions_locked()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._disconnect_all_locked()

    def _require_protocol(self, version: int, context) -> None:
        if version != PROTOCOL_VERSION:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"unsupported RPC protocol version {version}; expected {PROTOCOL_VERSION}",
            )

    def _require_mode_capability(self, mode: SessionMode) -> None:
        capability = Capability.OBSERVE if mode is SessionMode.OBSERVE else Capability.COMMAND
        if capability not in self.device.manifest.capabilities:
            raise LifecycleError(f"device does not expose the {capability.value} capability")

    def _require_session_locked(self, session_id: str) -> _Session:
        self._expire_sessions_locked()
        session = self._sessions.get(session_id)
        if session is None:
            raise LifecycleError("RPC session is missing or expired")
        session.last_seen = self._monotonic()
        return session

    def _require_command_session_locked(self, session_id: str) -> _Session:
        session = self._require_session_locked(session_id)
        if session.mode is not SessionMode.COMMAND:
            raise LifecycleError("session does not own command access")
        return session

    def _expire_sessions_locked(self) -> None:
        now = self._monotonic()
        command_session = self._sessions.get(self._command_session_id or "")
        if (
            command_session is not None
            and command_session.last_command is not None
            and now - command_session.last_command > self.command_timeout_s
        ):
            self._close_command_session_locked()
            now = self._monotonic()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.last_seen > self.lease_timeout_s
        ]
        if self._command_session_id in expired:
            self._close_command_session_locked()
            return
        for session_id in expired:
            del self._sessions[session_id]
        if expired and not self._sessions:
            self._disconnect_device_locked()

    def _disconnect_all_locked(self) -> None:
        had_command_session = self._command_session_id is not None
        self._sessions.clear()
        self._command_session_id = None
        release_error: Exception | None = None
        if had_command_session and isinstance(self.device, CommandLeaseDevice):
            try:
                self.device.release_command_lease()
            except Exception as exc:
                release_error = exc
        try:
            self._disconnect_device_locked()
        except Exception as exc:
            if release_error is not None:
                raise LifecycleError(
                    f"command release failed ({release_error}); device disconnect also failed ({exc})"
                ) from exc
            raise
        if release_error is not None:
            raise release_error

    def _close_command_session_locked(self) -> None:
        session_id = self._command_session_id
        if session_id is None:
            return
        self._sessions.pop(session_id, None)
        self._command_session_id = None
        if not isinstance(self.device, CommandLeaseDevice):
            self._sessions.clear()
            self._disconnect_device_locked()
            return
        try:
            self.device.release_command_lease()
        except Exception:
            self._sessions.clear()
            self._disconnect_device_locked()
            raise
        if not self._sessions:
            self._disconnect_device_locked()

    def _disconnect_device_locked(self) -> None:
        if self.device.is_connected:
            self.device.disconnect()


class DeviceRpcServer:
    """Serve one device over a local Unix socket without opening it at construction."""

    def __init__(
        self,
        device: OperationalDevice,
        *,
        endpoint: str,
        lease_timeout_s: float,
        command_timeout_s: float | None = None,
        max_workers: int = 8,
    ) -> None:
        if not math.isfinite(lease_timeout_s) or lease_timeout_s < 0.05:
            raise ValueError("lease_timeout_s must be finite and at least 0.05 seconds")
        if command_timeout_s is None:
            command_timeout_s = lease_timeout_s
        if (
            not math.isfinite(command_timeout_s)
            or command_timeout_s < 0.05
            or command_timeout_s > lease_timeout_s
        ):
            raise ValueError(
                "command_timeout_s must be finite, at least 0.05 seconds, "
                "and no greater than lease_timeout_s"
            )
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self.endpoint = endpoint
        self.socket_path = unix_socket_path(endpoint)
        self._service = _DeviceService(
            device,
            lease_timeout_s=lease_timeout_s,
            command_timeout_s=command_timeout_s,
        )
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
        device_pb2_grpc.add_DeviceServiceServicer_to_server(self._service, self._server)
        self._lease_timeout_s = lease_timeout_s
        self._stop_requested = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._started = False
        self._socket_identity: tuple[int, int] | None = None

    def start(self) -> None:
        if self._started or self._stop_requested.is_set():
            raise LifecycleError("device RPC server instances cannot be restarted")
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise LifecycleError(f"RPC socket path already exists: {self.socket_path}")
        if self._server.add_insecure_port(self.endpoint) == 0:
            raise LifecycleError(f"could not bind RPC endpoint: {self.endpoint}")
        self._server.start()
        try:
            socket_stat = os.lstat(self.socket_path)
        except OSError as exc:
            self._server.stop(0).wait(timeout=1.0)
            raise LifecycleError(
                f"RPC server started without creating its Unix socket: {self.socket_path}"
            ) from exc
        self._socket_identity = (socket_stat.st_dev, socket_stat.st_ino)
        self._started = True
        self._watchdog = threading.Thread(
            target=self._watchdog_loop,
            name="embodied-ops-lease-watchdog",
            daemon=True,
        )
        self._watchdog.start()

    def wait_for_termination(self, timeout: float | None = None) -> bool:
        if not self._started:
            raise LifecycleError("device RPC server is not started")
        return self._server.wait_for_termination(timeout)

    def stop(self, grace_s: float = 0.0) -> None:
        if not self._started:
            return
        self._stop_requested.set()
        disconnect_error: Exception | None = None
        try:
            self._service.close()
        except Exception as exc:
            disconnect_error = exc
        finally:
            event = self._server.stop(grace_s)
            event.wait(timeout=max(1.0, grace_s + 1.0))
            if self._watchdog is not None:
                self._watchdog.join(timeout=1.0)
            self._watchdog = None
            self._started = False
            self._remove_owned_socket()
        if disconnect_error is not None:
            raise LifecycleError(
                f"device disconnect failed while stopping RPC server: {disconnect_error}"
            ) from disconnect_error

    def _watchdog_loop(self) -> None:
        interval_s = min(0.25, self._lease_timeout_s / 4)
        while not self._stop_requested.wait(interval_s):
            try:
                self._service.expire_sessions()
            except Exception:
                # Device disconnect remains best-effort after a backend failure. RPC
                # calls still fail because the expired session has been removed.
                pass

    def _remove_owned_socket(self) -> None:
        try:
            socket_stat = os.lstat(self.socket_path)
        except FileNotFoundError:
            return
        identity = (socket_stat.st_dev, socket_stat.st_ino)
        if stat.S_ISSOCK(socket_stat.st_mode) and identity == self._socket_identity:
            self.socket_path.unlink()


class _CommandLeaseUnavailable(LifecycleError):
    pass


def _session_mode_from_proto(value: int) -> SessionMode:
    if value == device_pb2.SESSION_MODE_OBSERVE:
        return SessionMode.OBSERVE
    if value == device_pb2.SESSION_MODE_COMMAND:
        return SessionMode.COMMAND
    raise ContractError(f"unsupported RPC session mode: {value}")


def _validate_client_identity(name: str, version: str) -> None:
    if not name or name.strip() != name or any(character.isspace() for character in name):
        raise ContractError(f"invalid RPC client name: {name!r}")
    if (
        not version
        or version.strip() != version
        or any(character.isspace() for character in version)
    ):
        raise ContractError(f"invalid RPC client version: {version!r}")
