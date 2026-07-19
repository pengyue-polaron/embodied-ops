"""Public exception hierarchy for embodied-ops."""


class EmbodiedOpsError(Exception):
    """Base class for SDK errors."""


class ContractError(EmbodiedOpsError, ValueError):
    """A manifest, feature value, or backend violates the public contract."""


class BackendNotFoundError(EmbodiedOpsError, LookupError):
    """No installed backend is registered under the requested name."""


class BackendConflictError(EmbodiedOpsError):
    """More than one installed distribution owns the same backend name."""


class LifecycleError(EmbodiedOpsError, RuntimeError):
    """A device lifecycle operation is invalid or failed."""
