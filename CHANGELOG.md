# Changelog

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
