from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Mapping

import grpc
import pytest

from embodied_ops import (
    Capability,
    DeviceManifest,
    FeatureSpec,
    HealthReport,
    HealthStatus,
    RpcError,
)
from embodied_ops.rpc import DeviceRpcServer, RemoteDevice, SessionMode
from embodied_ops.rpc.types import PROTOCOL_VERSION
from embodied_ops.rpc.v1 import device_pb2, device_pb2_grpc

FEATURES = (FeatureSpec("joint.pos", unit="rad", minimum=-1.0, maximum=1.0),)


@dataclass
class FakeDevice:
    connected: bool = False
    connect_count: int = 0
    disconnect_count: int = 0
    command_acquire_count: int = 0
    command_release_count: int = 0
    command_lease_active: bool = False
    commands: list[dict[str, object]] = field(default_factory=list)
    fail_command: bool = False

    @property
    def manifest(self) -> DeviceManifest:
        return DeviceManifest(
            identifier="fake-arm",
            capabilities=(Capability.OBSERVE, Capability.COMMAND, Capability.HEALTH),
            observation_features=FEATURES,
            action_features=FEATURES,
        )

    @property
    def is_connected(self) -> bool:
        return self.connected

    def connect(self) -> None:
        self.connected = True
        self.connect_count += 1

    def observe(self) -> Mapping[str, object]:
        return {"joint.pos": 0.25}

    def acquire_command_lease(self) -> None:
        if self.command_lease_active:
            raise RuntimeError("command lease is already active")
        self.command_lease_active = True
        self.command_acquire_count += 1

    def release_command_lease(self) -> None:
        self.command_lease_active = False
        self.command_release_count += 1

    def command(self, action: Mapping[str, object]) -> Mapping[str, object]:
        if not self.command_lease_active:
            raise RuntimeError("command lease is not active")
        self.commands.append(dict(action))
        if self.fail_command:
            raise RuntimeError("injected command failure")
        return action

    def health(self) -> HealthReport:
        return HealthReport(HealthStatus.HEALTHY, "ready", {"feedback": True})

    def disconnect(self) -> None:
        self.connected = False
        self.disconnect_count += 1


def test_unix_rpc_round_trip_keeps_server_as_the_only_device_owner(tmp_path) -> None:
    endpoint = f"unix://{tmp_path / 'device.sock'}"
    device = FakeDevice()
    server = DeviceRpcServer(device, endpoint=endpoint, lease_timeout_s=1.0)
    server.start()
    command_client = RemoteDevice(endpoint=endpoint, client_name="test-command")
    observer = RemoteDevice(
        endpoint=endpoint,
        mode=SessionMode.OBSERVE,
        client_name="test-observer",
    )
    try:
        assert command_client.manifest.identifier == "fake-arm"
        assert device.connect_count == 0

        command_client.connect()
        observer.connect()
        assert device.connect_count == 1
        assert observer.observe() == {"joint.pos": 0.25}
        assert command_client.command({"joint.pos": 0.5}) == {"joint.pos": 0.5}
        assert command_client.health().details == {"feedback": True}

        command_client.disconnect()
        assert device.is_connected
        assert device.command_release_count == 1
        assert observer.observe() == {"joint.pos": 0.25}
        observer.disconnect()
        assert device.disconnect_count == 1
        assert device.commands == [{"joint.pos": 0.5}]
    finally:
        observer.disconnect()
        command_client.disconnect()
        server.stop()


def test_command_lease_is_exclusive_and_expiry_disconnects_device(tmp_path) -> None:
    endpoint = f"unix://{tmp_path / 'leased.sock'}"
    device = FakeDevice()
    server = DeviceRpcServer(device, endpoint=endpoint, lease_timeout_s=0.15)
    server.start()
    owner = RemoteDevice(endpoint=endpoint, client_name="owner")
    contender = RemoteDevice(endpoint=endpoint, client_name="contender")
    try:
        owner.connect()
        with pytest.raises(RpcError, match="RESOURCE_EXHAUSTED"):
            contender.connect()
        owner.disconnect()

        channel = grpc.insecure_channel(endpoint)
        stub = device_pb2_grpc.DeviceServiceStub(channel)
        stub.Open(
            device_pb2.OpenRequest(
                protocol_version=PROTOCOL_VERSION,
                mode=device_pb2.SESSION_MODE_COMMAND,
                client_name="abandoned-client",
                client_version="1.0",
            ),
            timeout=1.0,
        )
        deadline = time.monotonic() + 1.0
        while device.is_connected and time.monotonic() < deadline:
            time.sleep(0.01)
        channel.close()

        assert device.is_connected is False
        assert device.disconnect_count == 2
        assert device.command_acquire_count == 2
        assert device.command_release_count == 2
    finally:
        contender.disconnect()
        owner.disconnect()
        server.stop()


def test_command_failure_closes_the_remote_session_and_device(tmp_path) -> None:
    endpoint = f"unix://{tmp_path / 'failure.sock'}"
    device = FakeDevice(fail_command=True)
    server = DeviceRpcServer(device, endpoint=endpoint, lease_timeout_s=1.0)
    server.start()
    client = RemoteDevice(endpoint=endpoint, client_name="failing-client")
    try:
        client.connect()
        with pytest.raises(RpcError, match="session was closed"):
            client.command({"joint.pos": 0.5})

        assert client.is_connected is False
        assert device.is_connected is False
        assert device.disconnect_count == 1
        assert device.command_release_count == 1
    finally:
        client.disconnect()
        server.stop()


def test_command_inactivity_expires_even_while_heartbeats_keep_observers_alive(tmp_path) -> None:
    endpoint = f"unix://{tmp_path / 'command-deadman.sock'}"
    device = FakeDevice()
    server = DeviceRpcServer(
        device,
        endpoint=endpoint,
        lease_timeout_s=1.0,
        command_timeout_s=0.15,
    )
    server.start()
    owner = RemoteDevice(endpoint=endpoint, client_name="idle-owner")
    observer = RemoteDevice(
        endpoint=endpoint,
        mode=SessionMode.OBSERVE,
        client_name="surviving-observer",
    )
    try:
        owner.connect()
        observer.connect()
        deadline = time.monotonic() + 1.0
        while device.command_lease_active and time.monotonic() < deadline:
            time.sleep(0.01)

        assert device.command_lease_active is False
        assert device.is_connected is True
        assert observer.observe() == {"joint.pos": 0.25}
        with pytest.raises(RpcError, match="missing or expired"):
            owner.command({"joint.pos": 0.0})
    finally:
        owner.disconnect()
        observer.disconnect()
        server.stop()
