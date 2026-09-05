# Changelog

## Unreleased

- Publish bounded calibrated controller trajectories as native Foxglove 3D
  scenes with Right/Forward/Up axes and pause, dropout, and reset boundaries.

- Improve Operator Panel tabs on small screens with touch-sized, scroll-snap
  navigation, active-state underlines, hidden scrollbars, and automatic active
  tab centering while preserving the desktop segmented control.

## 0.10.3

- Add a source-neutral retry-recording-stage command for transactional
  multi-stage acquisition backends.
- Show a phase-aware **Retry Arm 2** control only while the sequential second
  pass is active.

## 0.10.2

- Add typed sequential dual-arm phase and replay progress to the Foxglove
  operator state, with phase-aware recording controls.

## 0.10.1

- Show concise Runtime-provided episode context and live capture progress in the
  Foxglove Collection Console, including a distinct preparing phase.
- Open generated Foxglove live-session links directly in the Web app instead of
  prompting for the desktop client.

## 0.10.0

- Add the canonical ZMQ-to-Foxglove gateway, compact React controls, and
  organization-layout publisher.
- Add source-neutral managed-session supervision for backend-owned teleoperation
  entry points.

## 0.9.0

- Add the robot-neutral Foxglove Collection Console with versioned, layout-
  supplied topic/service configuration.
- Add dependency-free Foxglove status sanitization, guarded-action validation,
  panel-state builders, and fail-closed organization layout upserts for Runtime
  repositories.
- Add dependency-free, hardware-neutral Cartesian teleoperation contracts and
  geometry helpers proven by ManiSkill and MuJoCo adapters.
- Add an optional ZeroMQ data plane with lossy latest-state PUB/SUB streams and
  acknowledged, idempotent DEALER/ROUTER operator commands.
- Launch the Operator Panel process-group supervisor by its installed path so
  workflows do not emit a `runpy` module-preload warning.
- Add semantic input phase/detail and an independent input-gate revision to the
  versioned Operator Panel presentation contract.
- Require exact run and input revisions for guarded input, and exact run identity
  for stop, rejecting stale, replayed, and cross-run requests.
- Expose shared-application HTTP server lifecycle hooks so a robot Runtime can
  attach a private native control adapter without creating a second workflow
  owner.
- Keep schema-1 and unversioned child events readable while emitting schema 2.
- Pin the Web build's transitive `nanoid` dependency to its patched release.

## 0.7.0

- Add shared hardware-independent validation for complete LeRobot v3 dataset
  graphs, with caller-provided task, feature, count, and statistics constraints.
- Add a format-only LeRobot v3-to-v2.1 builder with episode Parquet output,
  H.264 video slicing, geometry checks, and v2.1 metadata generation.
- Keep NumPy, pandas, and PyArrow behind the `lerobot-dataset` extra; FFmpeg is
  checked only when a dataset actually contains video.

## 0.6.0

- Standardize dependency-free CLI levels, status presentation, task selection,
  and collection Start/Save, Discard, and Quit interaction across robots.
- Add a strict versioned Operator Panel catalog schema and reusable form builders
  so adapters provide robot-specific values without redefining the Web contract.
- Add reusable evaluation progress, contract-digest, verified Hugging Face
  artifact-store, and pinned code-environment workflows.
- Require every Operator Panel adapter catalog to satisfy schema version 1.

## 0.5.1

- Add a strict create-only JSON task and prompt registry.
- Add normalized local camera-health contracts for Operator Panel adapters.

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
