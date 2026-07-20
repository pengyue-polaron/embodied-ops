from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pytest

from embodied_ops import (
    BackendNotFoundError,
    BackendRegistry,
    Capability,
    ContractError,
    DeviceManifest,
    FeatureSpec,
    HealthReport,
    HealthStatus,
    create_device,
    device_session,
    validate_feature_values,
)


JOINT = FeatureSpec("joint0.pos", unit="rad", minimum=-1.0, maximum=1.0)


def test_manifest_and_values_are_strict_and_do_not_clamp() -> None:
    manifest = DeviceManifest(
        identifier="fake-arm",
        capabilities=(Capability.OBSERVE, Capability.COMMAND, Capability.HEALTH),
        observation_features=(JOINT,),
        action_features=(JOINT,),
    )

    assert manifest.to_dict()["action_features"][0]["unit"] == "rad"
    assert validate_feature_values({"joint0.pos": 0.5}, manifest.action_features) == {
        "joint0.pos": 0.5
    }
    with pytest.raises(ContractError, match="above maximum"):
        validate_feature_values({"joint0.pos": 1.1}, manifest.action_features)
    with pytest.raises(ContractError, match="unknown feature"):
        validate_feature_values({"joint0.pos": 0.0, "surprise": 1.0}, manifest.action_features)


def test_manifest_rejects_ambiguous_features() -> None:
    with pytest.raises(ContractError, match="duplicate feature"):
        DeviceManifest(
            identifier="bad",
            capabilities=(Capability.OBSERVE,),
            observation_features=(JOINT, JOINT),
        )


@dataclass
class FakeDevice:
    connected: bool = False
    disconnect_count: int = 0

    @property
    def manifest(self) -> DeviceManifest:
        return DeviceManifest(
            identifier="fake",
            capabilities=(Capability.HEALTH,),
        )

    @property
    def is_connected(self) -> bool:
        return self.connected

    def connect(self) -> None:
        self.connected = True

    def health(self) -> HealthReport:
        return HealthReport(HealthStatus.HEALTHY, "ready")

    def disconnect(self) -> None:
        self.connected = False
        self.disconnect_count += 1


def _fake_factory(_config: Mapping[str, object]) -> FakeDevice:
    return FakeDevice()


def test_registry_creation_has_no_connection_side_effect() -> None:
    registry = BackendRegistry()
    registry.register("fake", _fake_factory)

    device = create_device("fake", registry=registry)

    assert device.is_connected is False
    assert registry.names() == ("fake",)
    with pytest.raises(BackendNotFoundError):
        create_device("missing", registry=registry)


def test_device_session_disconnects_after_failure() -> None:
    registry = BackendRegistry()
    created: list[FakeDevice] = []

    def factory(_config: Mapping[str, object]) -> FakeDevice:
        device = FakeDevice()
        created.append(device)
        return device

    registry.register("fake", factory)

    with pytest.raises(RuntimeError, match="boom"):
        with device_session("fake", registry=registry) as device:
            assert device.is_connected
            raise RuntimeError("boom")

    assert created[0].disconnect_count == 1
    assert created[0].is_connected is False
