# embodied-ops

`embodied-ops` is a small Python contract for composing embodied systems without
coupling applications to a particular robot framework or middleware. Its core remains
dependency-free; the `grpc` extra adds a versioned local service boundary.

It standardizes:

- capability-oriented device manifests;
- typed observation and action feature descriptions;
- strict, non-clamping scalar validation;
- lifecycle and health protocols;
- backend discovery through the standard `embodied_ops.backends` entry-point group;
- an optional Protobuf/gRPC transport over Unix-domain sockets.

It intentionally does **not** own ROS nodes, robot drivers, teleoperation mappings,
datasets, policy runtimes, process supervision, or safety limits. Those belong to
installed backends and application runtimes.

## Backend contract

An integration publishes a factory in `pyproject.toml`:

```toml
[project.entry-points."embodied_ops.backends"]
my_robot = "my_robot_runtime.backend:create_backend"
```

The factory accepts a plain mapping and returns an `OperationalDevice`. Constructing
the device must not open hardware; callers explicitly invoke `connect()` or use
`device_session()`.

```python
from embodied_ops import create_device

robot = create_device("my_robot", {"config": "robot.toml"})
robot.connect()
try:
    print(robot.manifest.to_dict())
    print(robot.health())
finally:
    robot.disconnect()
```

Additional capabilities are expressed structurally through `ObservableDevice`,
`CommandDevice`, `CalibratableDevice`, and `ResettableDevice`. Adapters such as
LeRobot plugins translate these contracts into their framework-native interfaces.

## RPC boundary

Install the optional transport when an adapter and its hardware runtime must live in
separate processes:

```bash
python -m pip install "embodied-ops[grpc]"
```

The runtime owns the real device and serves it; clients receive only the manifest and
capability operations:

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

robot = RemoteDevice(endpoint=endpoint, client_name="my-adapter")
robot.connect()
```

Protocol v1 provides describe, observe, command, health, calibration, and reset RPCs.
It carries scalar features and dependency-free typed tensor payloads. Command sessions
are exclusive and use opaque session ids, contiguous command sequence numbers,
monotonic timestamps, server-owned leases, and an independent command-inactivity
deadman. Heartbeats prove session liveness but do not keep an idle command lease alive.
Observe-only sessions may coexist. Devices that implement `CommandLeaseDevice` can
release their command resources while keeping read-only observation attached; other
devices retain the conservative disconnect-on-command-close behavior. The hardware
runtime remains responsible for its final fail-closed behavior.

Only absolute `unix:///` endpoints are accepted in v1. TCP/TLS policy is intentionally
not implied by the local protocol.

## Versioning

The Python package follows semantic versioning. `DeviceManifest.api_version` versions
the capability contract independently. The wire handshake has its own
`protocol_version`; both are currently version 1.

## Development

```bash
uv sync --extra grpc --dev
uv run pytest
uv run ruff check .
uv build
```

## License

Apache-2.0
