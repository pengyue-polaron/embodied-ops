"""Hardware-independent teleoperation contracts.

The core contracts and geometry helpers remain dependency-free. Import the
optional :mod:`embodied_ops.teleop.zmq_transport` module only in processes that
install the ``teleop-zmq`` extra.
"""

from .contracts import (
    COMMAND_RESULT_SCHEMA,
    COMMAND_SCHEMA,
    FEEDBACK_SCHEMA,
    SOURCE_STATUS_SCHEMA,
    TARGET_SCHEMA,
    TELEOP_COMMAND_NAMES,
    TeleopCommand,
    TeleopCommandName,
    TeleopCommandResult,
    TeleopFeedback,
    TeleopSourceStatus,
    TeleopTarget,
)
from .geometry import AXIS_NAMES, build_axis_map, matrix_to_quat_xyzw
from .mapping import CartesianClutchMapper, CartesianMappingResult
from .recording import (
    EPISODE_MANIFEST_SCHEMA,
    STEP_SCHEMA,
    TeleopEpisodeProvenance,
    atomic_write_json,
    build_episode_manifest,
    describe_artifact,
    sha256_file,
)
from .safety import CartesianTargetGuard, TargetGuardResult

__all__ = [
    "AXIS_NAMES",
    "COMMAND_RESULT_SCHEMA",
    "COMMAND_SCHEMA",
    "CartesianClutchMapper",
    "CartesianMappingResult",
    "CartesianTargetGuard",
    "EPISODE_MANIFEST_SCHEMA",
    "FEEDBACK_SCHEMA",
    "SOURCE_STATUS_SCHEMA",
    "STEP_SCHEMA",
    "TARGET_SCHEMA",
    "TELEOP_COMMAND_NAMES",
    "TargetGuardResult",
    "TeleopCommand",
    "TeleopCommandName",
    "TeleopCommandResult",
    "TeleopFeedback",
    "TeleopEpisodeProvenance",
    "TeleopSourceStatus",
    "TeleopTarget",
    "atomic_write_json",
    "build_axis_map",
    "build_episode_manifest",
    "describe_artifact",
    "matrix_to_quat_xyzw",
    "sha256_file",
]
