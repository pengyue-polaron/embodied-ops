"""Capability-oriented device contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable

from .errors import ContractError
from .features import FeatureSpec, index_features

API_VERSION = 1


class Capability(str, Enum):
    OBSERVE = "observe"
    COMMAND = "command"
    HEALTH = "health"
    CALIBRATE = "calibrate"
    RESET = "reset"
    CAMERA = "camera"


class HealthStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAULT = "fault"


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: HealthStatus
    summary: str
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary:
            raise ContractError("health summary must not be empty")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class DeviceManifest:
    """Backend-neutral description of one operational device."""

    identifier: str
    capabilities: tuple[Capability, ...]
    observation_features: tuple[FeatureSpec, ...] = ()
    action_features: tuple[FeatureSpec, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    api_version: int = API_VERSION

    def __post_init__(self) -> None:
        if not self.identifier or self.identifier.strip() != self.identifier:
            raise ContractError(f"invalid device identifier: {self.identifier!r}")
        if self.api_version != API_VERSION:
            raise ContractError(
                f"unsupported manifest API version {self.api_version}; expected {API_VERSION}"
            )
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ContractError("device capabilities must be unique")
        index_features(self.observation_features)
        index_features(self.action_features)
        if self.observation_features and Capability.OBSERVE not in self.capabilities:
            raise ContractError("observation features require the observe capability")
        if self.action_features and Capability.COMMAND not in self.capabilities:
            raise ContractError("action features require the command capability")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, object]:
        return {
            "api_version": self.api_version,
            "identifier": self.identifier,
            "capabilities": [capability.value for capability in self.capabilities],
            "observation_features": [feature.to_dict() for feature in self.observation_features],
            "action_features": [feature.to_dict() for feature in self.action_features],
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class OperationalDevice(Protocol):
    """Minimum lifecycle and health surface implemented by every backend."""

    @property
    def manifest(self) -> DeviceManifest: ...

    @property
    def is_connected(self) -> bool: ...

    def connect(self) -> None: ...

    def health(self) -> HealthReport: ...

    def disconnect(self) -> None: ...


@runtime_checkable
class ObservableDevice(OperationalDevice, Protocol):
    def observe(self) -> Mapping[str, object]: ...


@runtime_checkable
class CommandDevice(OperationalDevice, Protocol):
    def command(self, action: Mapping[str, object]) -> Mapping[str, object]: ...


@runtime_checkable
class CalibratableDevice(OperationalDevice, Protocol):
    @property
    def is_calibrated(self) -> bool: ...

    def calibrate(self) -> None: ...


@runtime_checkable
class ResettableDevice(OperationalDevice, Protocol):
    def reset(self, target: str | None = None) -> None: ...
