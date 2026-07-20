"""Strict protobuf conversion at the transport boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from embodied_ops.device import (
    Capability,
    DeviceManifest,
    HealthReport,
    HealthStatus,
)
from embodied_ops.errors import ContractError
from embodied_ops.features import (
    FeatureKind,
    FeatureSpec,
    index_features,
    validate_feature_values,
)
from embodied_ops.rpc.types import TensorValue
from embodied_ops.rpc.v1 import device_pb2


def manifest_to_proto(manifest: DeviceManifest) -> device_pb2.DeviceManifest:
    return device_pb2.DeviceManifest(
        api_version=manifest.api_version,
        identifier=manifest.identifier,
        capabilities=[capability.value for capability in manifest.capabilities],
        observation_features=[
            feature_to_proto(feature) for feature in manifest.observation_features
        ],
        action_features=[feature_to_proto(feature) for feature in manifest.action_features],
        metadata=dict(manifest.metadata),
    )


def manifest_from_proto(message: device_pb2.DeviceManifest) -> DeviceManifest:
    return DeviceManifest(
        api_version=message.api_version,
        identifier=message.identifier,
        capabilities=tuple(Capability(value) for value in message.capabilities),
        observation_features=tuple(
            feature_from_proto(feature) for feature in message.observation_features
        ),
        action_features=tuple(feature_from_proto(feature) for feature in message.action_features),
        metadata=dict(message.metadata),
    )


def feature_to_proto(feature: FeatureSpec) -> device_pb2.FeatureSpec:
    message = device_pb2.FeatureSpec(
        name=feature.name,
        kind=feature.kind.value,
        dtype=feature.dtype,
        shape=feature.shape,
    )
    if feature.unit is not None:
        message.unit = feature.unit
    if feature.minimum is not None:
        message.minimum = feature.minimum
    if feature.maximum is not None:
        message.maximum = feature.maximum
    return message


def feature_from_proto(message: device_pb2.FeatureSpec) -> FeatureSpec:
    return FeatureSpec(
        name=message.name,
        kind=FeatureKind(message.kind),
        dtype=message.dtype,
        shape=tuple(message.shape),
        unit=message.unit if message.HasField("unit") else None,
        minimum=message.minimum if message.HasField("minimum") else None,
        maximum=message.maximum if message.HasField("maximum") else None,
    )


def values_to_proto(
    values: Mapping[str, object], features: tuple[FeatureSpec, ...]
) -> list[device_pb2.FeatureValue]:
    validated = validate_feature_values(values, features)
    messages: list[device_pb2.FeatureValue] = []
    for feature in features:
        value = validated[feature.name]
        message = device_pb2.FeatureValue(name=feature.name)
        if feature.kind is FeatureKind.SCALAR:
            message.scalar = float(value)
        else:
            if not isinstance(value, TensorValue):
                raise ContractError(
                    f"feature {feature.name!r} requires an embodied_ops.rpc.TensorValue"
                )
            if value.dtype != feature.dtype or value.shape != feature.shape:
                raise ContractError(
                    f"feature {feature.name!r} tensor metadata does not match its manifest"
                )
            message.tensor.CopyFrom(
                device_pb2.TensorPayload(
                    dtype=value.dtype,
                    shape=value.shape,
                    data=value.data,
                )
            )
        messages.append(message)
    return messages


def values_from_proto(
    messages: Sequence[device_pb2.FeatureValue],
    features: tuple[FeatureSpec, ...],
) -> dict[str, object]:
    specs = index_features(features)
    values: dict[str, object] = {}
    for message in messages:
        if message.name in values:
            raise ContractError(f"duplicate feature value: {message.name!r}")
        try:
            feature = specs[message.name]
        except KeyError as exc:
            raise ContractError(f"unknown feature value: {message.name!r}") from exc
        payload = message.WhichOneof("payload")
        if feature.kind is FeatureKind.SCALAR:
            if payload != "scalar":
                raise ContractError(f"feature {message.name!r} requires a scalar payload")
            values[message.name] = message.scalar
        else:
            if payload != "tensor":
                raise ContractError(f"feature {message.name!r} requires a tensor payload")
            values[message.name] = TensorValue(
                dtype=message.tensor.dtype,
                shape=tuple(message.tensor.shape),
                data=bytes(message.tensor.data),
            )
    return validate_feature_values(values, features)


def health_to_proto(report: HealthReport) -> device_pb2.HealthResponse:
    details = Struct()
    try:
        ParseDict(dict(report.details), details)
    except (TypeError, ValueError) as exc:
        raise ContractError("health details must be protobuf-Struct compatible") from exc
    return device_pb2.HealthResponse(
        status=report.status.value,
        summary=report.summary,
        details=details,
    )


def health_from_proto(message: device_pb2.HealthResponse) -> HealthReport:
    return HealthReport(
        status=HealthStatus(message.status),
        summary=message.summary,
        details=MessageToDict(message.details),
    )
