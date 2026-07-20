<h1 align="center">embodied-ops</h1>

<p align="center">
  Framework-neutral contracts for embodied devices and local runtimes.
</p>

<p align="center">
  <a href="LICENSE"><img alt="Apache-2.0 License" src="https://img.shields.io/badge/License-Apache--2.0-blue.svg"></a>
</p>

`embodied-ops` is a small Python interface for composing robot systems without
coupling applications to a particular middleware or hardware framework. The
core package has no runtime dependencies. The optional `grpc` extra adds a
versioned process boundary over Unix-domain sockets.

## Install

```bash
python -m pip install embodied-ops
python -m pip install "embodied-ops[grpc]"
```

## Contracts

| Area | Public contract |
| --- | --- |
| Description | Device manifests and typed observation/action features |
| Capabilities | Observe, command, calibrate, reset, health, and lifecycle |
| Validation | Strict scalar validation without implicit clamping |
| Discovery | Standard `embodied_ops.backends` Python entry points |
| Transport | Optional Protobuf/gRPC protocol over absolute Unix sockets |

ROS nodes, drivers, teleoperation mappings, datasets, policies, safety limits,
and process supervision stay in hardware backends or application runtimes.

## Backend discovery

A backend exposes one factory in `pyproject.toml`:

```toml
[project.entry-points."embodied_ops.backends"]
my_robot = "my_robot_runtime.backend:create_backend"
```

The factory accepts a plain mapping and returns an `OperationalDevice`.
Construction must not open hardware; connection remains explicit.

```python
from embodied_ops import device_session

with device_session("my_robot", {"config": "robot.toml"}) as device:
    print(device.manifest.to_dict())
    print(device.health())
```

Optional capabilities are represented by `ObservableDevice`, `CommandDevice`,
`CalibratableDevice`, and `ResettableDevice`. Framework adapters translate
these interfaces into their native Robot or Teleoperator APIs.

## Local RPC

The Runtime owns the device and serves it; the adapter receives only the
manifest and supported operations.

```python
from embodied_ops.rpc import DeviceRpcServer, RemoteDevice

endpoint = "unix:///run/my-robot/device.sock"
server = DeviceRpcServer(
    device,
    endpoint=endpoint,
    lease_timeout_s=1.0,
    command_timeout_s=0.5,
)
server.start()

client = RemoteDevice(endpoint=endpoint, client_name="my-adapter")
client.connect()
```

Protocol v1 supports describe, observe, command, health, calibration, and reset.
Command sessions are exclusive and carry session IDs, contiguous sequence
numbers, monotonic timestamps, server-owned leases, and an independent command
deadman. Heartbeats keep a session alive but do not extend an idle command
lease. Observe-only sessions may coexist.

Only absolute `unix:///` endpoints are accepted. Network transport and the
hardware Runtime's final fail-closed behavior are outside this protocol.

## Versioning

The package follows semantic versioning. `DeviceManifest.api_version` versions
the capability contract; `protocol_version` versions the wire handshake. Both
are currently version 1.

## Development

```bash
uv sync --extra grpc --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```
