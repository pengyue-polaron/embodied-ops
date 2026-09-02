"""Small dependency-free geometry helpers shared by teleop adapters."""

from __future__ import annotations

import math
from typing import Any

AXIS_VECTORS: dict[str, tuple[float, float, float]] = {
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
}
AXIS_NAMES = tuple(AXIS_VECTORS)


def build_axis_map(right_axis: str, forward_axis: str, up_axis: str) -> list[list[float]]:
    """Map source ``[right, forward, up]`` into one target-world xyz frame."""

    try:
        columns = [
            AXIS_VECTORS[right_axis],
            AXIS_VECTORS[forward_axis],
            AXIS_VECTORS[up_axis],
        ]
    except KeyError as exc:
        raise ValueError(f"unsupported axis name: {exc.args[0]}") from exc
    matrix = [[columns[column][row] for column in range(3)] for row in range(3)]
    determinant = (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )
    if abs(determinant) < 1e-6:
        raise ValueError("right/forward/up axes must be orthogonal and non-degenerate")
    return matrix


def matrix_to_quat_xyzw(matrix: Any) -> list[float]:
    """Convert a 3x3 rotation matrix into one normalized xyzw quaternion."""

    value = [[float(matrix[row][column]) for column in range(3)] for row in range(3)]
    trace = value[0][0] + value[1][1] + value[2][2]
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        qw = 0.25 * scale
        qx = (value[2][1] - value[1][2]) / scale
        qy = (value[0][2] - value[2][0]) / scale
        qz = (value[1][0] - value[0][1]) / scale
    elif value[0][0] > value[1][1] and value[0][0] > value[2][2]:
        scale = math.sqrt(max(0.0, 1.0 + value[0][0] - value[1][1] - value[2][2])) * 2.0
        qx = 0.25 * scale
        qy = (value[0][1] + value[1][0]) / scale
        qz = (value[0][2] + value[2][0]) / scale
        qw = (value[2][1] - value[1][2]) / scale
    elif value[1][1] > value[2][2]:
        scale = math.sqrt(max(0.0, 1.0 + value[1][1] - value[0][0] - value[2][2])) * 2.0
        qx = (value[0][1] + value[1][0]) / scale
        qy = 0.25 * scale
        qz = (value[1][2] + value[2][1]) / scale
        qw = (value[0][2] - value[2][0]) / scale
    else:
        scale = math.sqrt(max(0.0, 1.0 + value[2][2] - value[0][0] - value[1][1])) * 2.0
        qx = (value[0][2] + value[2][0]) / scale
        qy = (value[1][2] + value[2][1]) / scale
        qz = 0.25 * scale
        qw = (value[1][0] - value[0][1]) / scale
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm <= 1e-12:
        return [0.0, 0.0, 0.0, 1.0]
    return [qx / norm, qy / norm, qz / norm, qw / norm]
