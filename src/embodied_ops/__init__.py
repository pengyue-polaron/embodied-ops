"""Public capability protocols for embodied systems."""

from ._version import __version__
from .device import (
    API_VERSION,
    CalibratableDevice,
    Capability,
    CommandDevice,
    DeviceManifest,
    HealthReport,
    HealthStatus,
    ObservableDevice,
    OperationalDevice,
    ResettableDevice,
)
from .errors import (
    BackendConflictError,
    BackendNotFoundError,
    ContractError,
    EmbodiedOpsError,
    LifecycleError,
    RpcError,
)
from .endpoints import unix_socket_path
from .features import FeatureKind, FeatureSpec, index_features, validate_feature_values
from .registry import (
    BACKEND_ENTRY_POINT_GROUP,
    BackendFactory,
    BackendRegistry,
    create_device,
    default_registry,
    device_session,
)

__all__ = [
    "API_VERSION",
    "BACKEND_ENTRY_POINT_GROUP",
    "BackendConflictError",
    "BackendFactory",
    "BackendNotFoundError",
    "BackendRegistry",
    "CalibratableDevice",
    "Capability",
    "CommandDevice",
    "ContractError",
    "DeviceManifest",
    "EmbodiedOpsError",
    "FeatureKind",
    "FeatureSpec",
    "HealthReport",
    "HealthStatus",
    "LifecycleError",
    "ObservableDevice",
    "OperationalDevice",
    "ResettableDevice",
    "RpcError",
    "__version__",
    "create_device",
    "default_registry",
    "device_session",
    "index_features",
    "validate_feature_values",
    "unix_socket_path",
]
