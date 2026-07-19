# embodied-ops

`embodied-ops` is a small, dependency-free Python contract for composing embodied
systems without coupling applications to a particular robot framework, middleware,
or transport.

It standardizes:

- capability-oriented device manifests;
- typed observation and action feature descriptions;
- strict, non-clamping scalar validation;
- lifecycle and health protocols;
- backend discovery through the standard `embodied_ops.backends` entry-point group.

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

## Versioning

The Python package follows semantic versioning. `DeviceManifest.api_version` versions
the cross-package contract independently; version 1 is intentionally minimal.

## Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv build
```

## License

Apache-2.0
