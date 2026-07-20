"""Backend discovery through standard Python package entry points."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from importlib import metadata

from .device import OperationalDevice
from .errors import BackendConflictError, BackendNotFoundError, ContractError

BACKEND_ENTRY_POINT_GROUP = "embodied_ops.backends"
BackendFactory = Callable[[Mapping[str, object]], OperationalDevice]


class BackendRegistry:
    """Resolve local factories and installed backend entry points by stable name."""

    def __init__(self) -> None:
        self._local: dict[str, BackendFactory] = {}

    def register(self, name: str, factory: BackendFactory) -> None:
        if not name or name.strip() != name or any(character.isspace() for character in name):
            raise ContractError(f"invalid backend name: {name!r}")
        if name in self._local:
            raise BackendConflictError(f"backend {name!r} is already registered locally")
        self._local[name] = factory

    def unregister(self, name: str) -> None:
        self._local.pop(name, None)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._local) | {entry.name for entry in self._entry_points()}))

    def load(self, name: str) -> BackendFactory:
        if name in self._local:
            return self._local[name]
        matches = [entry for entry in self._entry_points() if entry.name == name]
        if not matches:
            raise BackendNotFoundError(
                f"backend {name!r} is not installed; available backends: {list(self.names())}"
            )
        if len(matches) > 1:
            owners = sorted(
                entry.dist.name if entry.dist is not None else "unknown" for entry in matches
            )
            raise BackendConflictError(
                f"backend {name!r} is provided by multiple packages: {owners}"
            )
        factory = matches[0].load()
        if not callable(factory):
            raise ContractError(f"backend entry point {name!r} did not load a callable factory")
        return factory

    @staticmethod
    def _entry_points() -> tuple[metadata.EntryPoint, ...]:
        return tuple(metadata.entry_points(group=BACKEND_ENTRY_POINT_GROUP))


default_registry = BackendRegistry()


def create_device(
    backend: str,
    config: Mapping[str, object] | None = None,
    *,
    registry: BackendRegistry = default_registry,
) -> OperationalDevice:
    """Instantiate an installed backend without connecting to hardware."""

    device = registry.load(backend)(dict(config or {}))
    if not isinstance(device, OperationalDevice):
        raise ContractError(f"backend {backend!r} does not implement OperationalDevice")
    return device


@contextmanager
def device_session(
    backend: str,
    config: Mapping[str, object] | None = None,
    *,
    registry: BackendRegistry = default_registry,
) -> Iterator[OperationalDevice]:
    """Connect a backend and guarantee disconnect after success or failure."""

    device = create_device(backend, config, registry=registry)
    device.connect()
    try:
        yield device
    finally:
        device.disconnect()
