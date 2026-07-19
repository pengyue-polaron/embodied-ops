"""Feature manifests and hardware-free value validation."""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .errors import ContractError


class FeatureKind(str, Enum):
    """Portable feature categories understood by SDK adapters."""

    SCALAR = "scalar"
    VECTOR = "vector"
    IMAGE = "image"


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Describes one named observation or action feature."""

    name: str
    kind: FeatureKind = FeatureKind.SCALAR
    dtype: str = "float32"
    shape: tuple[int, ...] = ()
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if not self.name or self.name.strip() != self.name or any(c.isspace() for c in self.name):
            raise ContractError(f"invalid feature name: {self.name!r}")
        if not self.dtype:
            raise ContractError(f"feature {self.name!r} requires a dtype")
        if any(not isinstance(size, int) or isinstance(size, bool) or size <= 0 for size in self.shape):
            raise ContractError(f"feature {self.name!r} has an invalid shape: {self.shape!r}")
        if self.kind is FeatureKind.SCALAR and self.shape:
            raise ContractError(f"scalar feature {self.name!r} must have shape=()")
        if self.kind is not FeatureKind.SCALAR and not self.shape:
            raise ContractError(f"{self.kind.value} feature {self.name!r} requires a shape")
        for label, value in (("minimum", self.minimum), ("maximum", self.maximum)):
            if value is not None and not math.isfinite(float(value)):
                raise ContractError(f"feature {self.name!r} has non-finite {label}")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ContractError(f"feature {self.name!r} minimum exceeds maximum")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "dtype": self.dtype,
            "shape": list(self.shape),
            "unit": self.unit,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


def index_features(features: tuple[FeatureSpec, ...]) -> Mapping[str, FeatureSpec]:
    """Return an immutable name index and reject ambiguous manifests."""

    indexed: dict[str, FeatureSpec] = {}
    for feature in features:
        if feature.name in indexed:
            raise ContractError(f"duplicate feature name: {feature.name!r}")
        indexed[feature.name] = feature
    return MappingProxyType(indexed)


def validate_feature_values(
    values: Mapping[str, object],
    features: tuple[FeatureSpec, ...],
    *,
    exact: bool = True,
) -> dict[str, object]:
    """Validate a feature mapping without rewriting or clamping it.

    Scalar values are checked exhaustively. Vector and image payload ownership stays
    with the backend because this dependency-free SDK does not impose an array library.
    """

    specs = index_features(features)
    keys = set(values)
    expected = set(specs)
    missing = expected - keys
    unknown = keys - expected
    if missing:
        raise ContractError(f"missing feature values: {sorted(missing)}")
    if exact and unknown:
        raise ContractError(f"unknown feature values: {sorted(unknown)}")

    validated: dict[str, object] = {}
    for name, spec in specs.items():
        value = values[name]
        if spec.kind is FeatureKind.SCALAR:
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise ContractError(f"feature {name!r} must be a real scalar")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ContractError(f"feature {name!r} must be finite")
            if spec.minimum is not None and numeric < spec.minimum:
                raise ContractError(f"feature {name!r} is below minimum {spec.minimum}")
            if spec.maximum is not None and numeric > spec.maximum:
                raise ContractError(f"feature {name!r} is above maximum {spec.maximum}")
        validated[name] = value
    if not exact:
        validated.update((name, values[name]) for name in unknown)
    return validated
