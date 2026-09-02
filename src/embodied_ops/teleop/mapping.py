"""Backend-independent relative-clutch Cartesian target mapping."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .contracts import TeleopTarget
from .safety import CartesianTargetGuard, TargetGuardResult

Matrix3 = list[list[float]]
Vector3 = list[float]


def _vector3(value: object, name: str) -> Vector3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain three values")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} must contain finite values")
    return result


def _matrix3(value: object, name: str) -> Matrix3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must be a 3x3 matrix")
    return [_vector3(row, f"{name}[{index}]") for index, row in enumerate(value)]


def _orthogonal_matrix3(value: object, name: str, *, proper: bool) -> Matrix3:
    matrix = _matrix3(value, name)
    tolerance = 1e-3
    transpose = _transpose(matrix)
    product = _matmul(matrix, transpose)
    if any(
        abs(product[row][column] - (1.0 if row == column else 0.0)) > tolerance
        for row in range(3)
        for column in range(3)
    ):
        raise ValueError(f"{name} must be orthogonal")
    determinant = (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )
    expected = 1.0 if proper else abs(determinant)
    if abs(expected - 1.0) > tolerance or (proper and abs(determinant - 1.0) > tolerance):
        qualifier = "a proper rotation" if proper else "orthogonal"
        raise ValueError(f"{name} must be {qualifier}")
    return matrix


def _transpose(matrix: Matrix3) -> Matrix3:
    return [[matrix[column][row] for column in range(3)] for row in range(3)]


def _matmul(left: Matrix3, right: Matrix3) -> Matrix3:
    return [
        [sum(left[row][k] * right[k][column] for k in range(3)) for column in range(3)]
        for row in range(3)
    ]


def _matvec(matrix: Matrix3, vector: Vector3) -> Vector3:
    return [sum(matrix[row][column] * vector[column] for column in range(3)) for row in range(3)]


@dataclass(frozen=True, slots=True)
class CartesianMappingResult:
    desired_position: Vector3
    desired_rotation: Matrix3
    gripper: float
    target_age_ms: float | None
    saturated: bool
    reason: str
    guard: TargetGuardResult


@dataclass(slots=True)
class _ClutchHome:
    source_position: Vector3
    source_rotation: Matrix3
    eef_position: Vector3
    eef_rotation: Matrix3


class CartesianClutchMapper:
    """Map canonical target motion relative to the EEF pose at clutch-in."""

    def __init__(
        self,
        *,
        teleop_to_world: object,
        position_scale: float,
        workspace_half_extent: object,
        orientation: bool,
        max_target_age_ms: float = 250.0,
        recovery_frames: int = 6,
        max_input_gap_ms: float = 200.0,
        max_position_step_m: float = 0.06,
        max_position_speed_m_s: float = 3.0,
        position_deadband_m: float = 0.001,
        position_filter_tau_s: float = 0.05,
        max_target_speed_m_s: float = 0.5,
    ) -> None:
        scale = float(position_scale)
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("position_scale must be finite and positive")
        extent = _vector3(workspace_half_extent, "workspace_half_extent")
        if any(item <= 0 for item in extent):
            raise ValueError("workspace_half_extent values must be positive")
        self.teleop_to_world = _orthogonal_matrix3(teleop_to_world, "teleop_to_world", proper=False)
        self.position_scale = scale
        self.workspace_half_extent = extent
        self.orientation = bool(orientation)
        self.guard = CartesianTargetGuard(
            max_target_age_ms=max_target_age_ms,
            recovery_frames=recovery_frames,
            max_input_gap_ms=max_input_gap_ms,
            max_position_step_m=max_position_step_m,
            max_position_speed_m_s=max_position_speed_m_s,
            guard_rotation=orientation,
            position_deadband_m=position_deadband_m,
            position_filter_tau_s=position_filter_tau_s,
            max_output_speed_m_s=max_target_speed_m_s,
        )
        self.force_hold = False
        self.gripper = 1.0
        self._home: _ClutchHome | None = None
        self._initial_eef_position: Vector3 | None = None

    @property
    def initial_eef_position(self) -> Vector3 | None:
        value = self._initial_eef_position
        return None if value is None else value.copy()

    def reset_clutch(self) -> None:
        self._home = None

    def reset_episode(self) -> None:
        self._home = None
        self._initial_eef_position = None
        self.guard.reset()

    def update(
        self,
        target: TeleopTarget | None,
        *,
        target_received_monotonic_ns: int | None,
        eef_position: object,
        eef_rotation: object,
    ) -> CartesianMappingResult:
        position = _vector3(eef_position, "eef_position")
        rotation = _orthogonal_matrix3(eef_rotation, "eef_rotation", proper=True)
        if self._initial_eef_position is None:
            self._initial_eef_position = position.copy()
        guarded = self.guard.update(
            target,
            target_received_monotonic_ns=target_received_monotonic_ns,
        )
        if not guarded.ready or guarded.target is None or self.force_hold:
            self.reset_clutch()
            return CartesianMappingResult(
                desired_position=position,
                desired_rotation=rotation,
                gripper=self.gripper,
                target_age_ms=guarded.target_age_ms,
                saturated=False,
                reason="operator_hold" if self.force_hold else guarded.reason,
                guard=guarded,
            )

        sample = guarded.target
        self.gripper = float(sample.gripper)
        source_position = _vector3(sample.position, "target position")
        source_rotation = _orthogonal_matrix3(sample.rotation, "target rotation", proper=True)
        if self._home is None:
            self._home = _ClutchHome(
                source_position=source_position.copy(),
                source_rotation=[row.copy() for row in source_rotation],
                eef_position=position.copy(),
                eef_rotation=[row.copy() for row in rotation],
            )

        displacement = [
            (source_position[index] - self._home.source_position[index]) * self.position_scale
            for index in range(3)
        ]
        world_displacement = _matvec(self.teleop_to_world, displacement)
        unbounded = [
            self._home.eef_position[index] + world_displacement[index] for index in range(3)
        ]
        assert self._initial_eef_position is not None
        lower = [
            self._initial_eef_position[index] - self.workspace_half_extent[index]
            for index in range(3)
        ]
        upper = [
            self._initial_eef_position[index] + self.workspace_half_extent[index]
            for index in range(3)
        ]
        desired_position = [
            min(upper[index], max(lower[index], unbounded[index])) for index in range(3)
        ]
        saturated = any(
            abs(unbounded[index] - desired_position[index]) > 1e-10 for index in range(3)
        )

        if self.orientation:
            relative = _matmul(source_rotation, _transpose(self._home.source_rotation))
            world_relative = _matmul(
                _matmul(self.teleop_to_world, relative), _transpose(self.teleop_to_world)
            )
            desired_rotation = _matmul(world_relative, self._home.eef_rotation)
        else:
            desired_rotation = rotation

        return CartesianMappingResult(
            desired_position=desired_position,
            desired_rotation=desired_rotation,
            gripper=self.gripper,
            target_age_ms=guarded.target_age_ms,
            saturated=saturated,
            reason="active",
            guard=guarded,
        )
