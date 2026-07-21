# Changelog

## 0.5.0

- Make repository document creation format-driven instead of assuming TOML.
- Reduce `PanelAdapter` to catalog and workflow launch responsibilities; camera,
  configuration, and registration behavior now use independent optional providers.
- Add public protocol-event log filtering so consumers do not depend on wire prefixes.
- Remove the superseded configuration-store names and contracts.

## 0.4.0

- Add the adapter-driven Operator Panel with exclusive subprocess ownership,
  guarded input, typed progress, create-only configuration storage, and packaged
  Web assets.
- Keep repository discovery, validation, hardware commands, cameras, and safety
  behavior behind the consuming repository's adapter.

## 0.3.0

- Focus the package on collection, evaluation, and artifact workflows.
- Add transactional directory/file publication and create-only report helpers.
- Add portable episode decisions, sample freshness/skew checks, and deterministic
  evaluation plans.
- Remove the experimental generic device capability, backend discovery, and RPC APIs.
  Hardware integrations should use their framework-native interfaces and keep
  transport details robot-specific.

## 0.2.0

- Add a versioned Protobuf/gRPC device protocol over absolute Unix sockets.
- Add thin `RemoteDevice` clients and fail-closed `DeviceRpcServer` hosting.
- Add exclusive command leases, observation-only sessions, heartbeats, sequence and
  monotonic timestamp checks, and dependency-free tensor payloads.
- Separate optional command-resource ownership from the observation lifecycle and
  expire idle command sessions independently of heartbeat/session liveness.
- Keep gRPC and Protobuf optional through the `grpc` package extra.

## 0.1.0

- Define capability, manifest, health, and lifecycle contracts.
- Add strict scalar feature validation without implicit rewriting.
- Add backend discovery via `embodied_ops.backends` entry points.
