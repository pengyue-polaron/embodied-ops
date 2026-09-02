"""Hardware-independent teleoperation contracts.

The core contracts and geometry helpers remain dependency-free. Import the
optional :mod:`embodied_ops.teleop.zmq_transport` module only in processes that
install the ``teleop-zmq`` extra.
"""

from .contracts import (
    COMMAND_RESULT_SCHEMA,
    COMMAND_SCHEMA,
    FEEDBACK_SCHEMA,
    TARGET_SCHEMA,
    TeleopCommand,
    TeleopCommandResult,
    TeleopFeedback,
    TeleopTarget,
)
from .geometry import AXIS_NAMES, build_axis_map, matrix_to_quat_xyzw

__all__ = [
    "AXIS_NAMES",
    "COMMAND_RESULT_SCHEMA",
    "COMMAND_SCHEMA",
    "FEEDBACK_SCHEMA",
    "TARGET_SCHEMA",
    "TeleopCommand",
    "TeleopCommandResult",
    "TeleopFeedback",
    "TeleopTarget",
    "build_axis_map",
    "matrix_to_quat_xyzw",
]
