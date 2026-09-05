"""Source-neutral motion guards for Cartesian teleoperation targets."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace

from .contracts import TeleopTarget


def _distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)))


def _rotation_distance(left: list[list[float]], right: list[list[float]]) -> float:
    relative_trace = sum(
        float(left[row][column]) * float(right[row][column])
        for row in range(3)
        for column in range(3)
    )
    cosine = max(-1.0, min(1.0, (relative_trace - 1.0) * 0.5))
    return math.acos(cosine)


@dataclass(frozen=True, slots=True)
class TargetGuardResult:
    """One guarded target decision and its operator-facing evidence."""

    target: TeleopTarget | None
    state: str
    reason: str
    ready: bool
    reanchored: bool
    recovery_frames: int
    recovery_frames_required: int
    target_age_ms: float | None
    position_step_m: float | None
    position_speed_m_s: float | None
    rotation_step_rad: float | None
    jump_rejections: int

    def diagnostics(self) -> dict[str, object]:
        return {
            "guard_state": self.state,
            "guard_reason": self.reason,
            "guard_ready": self.ready,
            "guard_reanchored": self.reanchored,
            "recovery_frames": self.recovery_frames,
            "recovery_frames_required": self.recovery_frames_required,
            "position_step_m": self.position_step_m,
            "position_speed_m_s": self.position_speed_m_s,
            "rotation_step_rad": self.rotation_step_rad,
            "jump_rejections": self.jump_rejections,
        }


class CartesianTargetGuard:
    """Fail closed across dropouts and smooth plausible Cartesian motion.

    The guard deliberately operates on the canonical target rather than a
    device-specific packet.  A source may stop publishing, publish an explicit
    ``tracking_valid=False`` sample, or reconnect with a discontinuous pose;
    all three cases enter a short recovery window.  The first ready target
    after recovery is a re-anchor point, so downstream clutch mappers cannot
    chase a stale pre-dropout pose.
    """

    def __init__(
        self,
        *,
        max_target_age_ms: float = 250.0,
        recovery_frames: int = 6,
        max_input_gap_ms: float = 200.0,
        max_position_step_m: float = 0.06,
        max_position_speed_m_s: float = 3.0,
        max_rotation_step_rad: float = 1.2,
        max_rotation_speed_rad_s: float = 12.0,
        guard_rotation: bool = True,
        position_deadband_m: float = 0.001,
        position_filter_tau_s: float = 0.05,
        max_output_speed_m_s: float = 0.5,
    ) -> None:
        if recovery_frames < 1:
            raise ValueError("recovery_frames must be positive")
        positive = {
            "max_target_age_ms": max_target_age_ms,
            "max_input_gap_ms": max_input_gap_ms,
            "max_position_step_m": max_position_step_m,
            "max_position_speed_m_s": max_position_speed_m_s,
            "max_rotation_step_rad": max_rotation_step_rad,
            "max_rotation_speed_rad_s": max_rotation_speed_rad_s,
            "position_filter_tau_s": position_filter_tau_s,
            "max_output_speed_m_s": max_output_speed_m_s,
        }
        for name, value in positive.items():
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(float(position_deadband_m)) or position_deadband_m < 0:
            raise ValueError("position_deadband_m must be finite and non-negative")

        self.max_target_age_ms = float(max_target_age_ms)
        self.recovery_frames_required = int(recovery_frames)
        self.max_input_gap_ms = float(max_input_gap_ms)
        self.max_position_step_m = float(max_position_step_m)
        self.max_position_speed_m_s = float(max_position_speed_m_s)
        self.max_rotation_step_rad = float(max_rotation_step_rad)
        self.max_rotation_speed_rad_s = float(max_rotation_speed_rad_s)
        self.guard_rotation = bool(guard_rotation)
        self.position_deadband_m = float(position_deadband_m)
        self.position_filter_tau_s = float(position_filter_tau_s)
        self.max_output_speed_m_s = float(max_output_speed_m_s)
        self.jump_rejections = 0
        self.reset()

    def reset(self) -> None:
        self.state = "waiting"
        self.reason = "waiting_for_target"
        self.ready = False
        self.recovery_frames = 0
        self._last_token: tuple[object, ...] | None = None
        self._last_input_position: list[float] | None = None
        self._last_input_rotation: list[list[float]] | None = None
        self._last_input_monotonic_ns: int | None = None
        self._filtered_position: list[float] | None = None
        self._last_output_target: TeleopTarget | None = None

    def _invalidate(self, reason: str) -> None:
        self.state = "holding"
        self.reason = reason
        self.ready = False
        self.recovery_frames = 0
        self._last_input_position = None
        self._last_input_rotation = None
        self._last_input_monotonic_ns = None
        self._filtered_position = None
        self._last_output_target = None

    def _result(
        self,
        *,
        target: TeleopTarget | None,
        age_ms: float | None,
        reanchored: bool = False,
        position_step_m: float | None = None,
        position_speed_m_s: float | None = None,
        rotation_step_rad: float | None = None,
    ) -> TargetGuardResult:
        return TargetGuardResult(
            target=target,
            state=self.state,
            reason=self.reason,
            ready=self.ready,
            reanchored=reanchored,
            recovery_frames=self.recovery_frames,
            recovery_frames_required=self.recovery_frames_required,
            target_age_ms=age_ms,
            position_step_m=position_step_m,
            position_speed_m_s=position_speed_m_s,
            rotation_step_rad=rotation_step_rad,
            jump_rejections=self.jump_rejections,
        )

    def update(
        self,
        target: TeleopTarget | None,
        *,
        target_received_monotonic_ns: int | None = None,
        now_monotonic_ns: int | None = None,
    ) -> TargetGuardResult:
        now_ns = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
        if target is None:
            self._invalidate("waiting_for_target")
            return self._result(target=None, age_ms=None)

        input_ns = target.host_received_monotonic_ns or target_received_monotonic_ns
        age_ms = None if input_ns is None else max(0.0, (now_ns - input_ns) / 1_000_000.0)
        alignment = target.source_metadata.get("alignment")
        token = (
            target.session_id,
            target.seq,
            target.host_published_unix_ns,
            target.gate_open,
            target.tracking_valid,
            alignment.get("revision") if isinstance(alignment, dict) else None,
        )

        if age_ms is not None and age_ms > self.max_target_age_ms:
            self._last_token = token
            self._invalidate("stale_target")
            return self._result(target=None, age_ms=age_ms)
        if not target.tracking_valid:
            self._last_token = token
            self._invalidate("tracking_invalid")
            return self._result(target=None, age_ms=age_ms)
        if target.source_metadata.get("calibration_valid") is False:
            self._last_token = token
            self._invalidate("calibration_required")
            return self._result(target=None, age_ms=age_ms)
        if not target.gate_open:
            self._last_token = token
            self._invalidate("clutch_released")
            return self._result(target=None, age_ms=age_ms)

        if token == self._last_token:
            return self._result(target=self._last_output_target, age_ms=age_ms)

        position = [float(value) for value in target.position]
        rotation = [[float(value) for value in row] for row in target.rotation]
        position_step_m = None
        position_speed_m_s = None
        rotation_step_rad = None
        input_gap_ms = None
        if self._last_input_monotonic_ns is not None and input_ns is not None:
            input_gap_ms = max(0.0, (input_ns - self._last_input_monotonic_ns) / 1_000_000.0)
        if self._last_input_position is not None:
            position_step_m = _distance(position, self._last_input_position)
            if input_gap_ms is not None and input_gap_ms > 0:
                position_speed_m_s = position_step_m / (input_gap_ms / 1000.0)
        if self.guard_rotation and self._last_input_rotation is not None:
            rotation_step_rad = _rotation_distance(rotation, self._last_input_rotation)

        session_changed = bool(
            self._last_token is not None and target.session_id != self._last_token[0]
        )
        alignment_changed = bool(self._last_token is not None and token[5] != self._last_token[5])
        input_gap = input_gap_ms is not None and input_gap_ms > self.max_input_gap_ms
        position_jump = bool(
            position_step_m is not None
            and (
                position_step_m > self.max_position_step_m
                or (
                    position_speed_m_s is not None
                    and position_speed_m_s > self.max_position_speed_m_s
                )
            )
        )
        rotation_speed = (
            None
            if rotation_step_rad is None or input_gap_ms is None or input_gap_ms <= 0
            else rotation_step_rad / (input_gap_ms / 1000.0)
        )
        rotation_jump = bool(
            rotation_step_rad is not None
            and (
                rotation_step_rad > self.max_rotation_step_rad
                or (rotation_speed is not None and rotation_speed > self.max_rotation_speed_rad_s)
            )
        )

        discontinuity_reason = None
        if session_changed:
            discontinuity_reason = "source_session_changed"
        elif alignment_changed:
            discontinuity_reason = "calibration_changed"
        elif input_gap:
            discontinuity_reason = "input_gap"
        elif position_jump:
            discontinuity_reason = "position_jump"
        elif rotation_jump:
            discontinuity_reason = "rotation_jump"

        if discontinuity_reason is not None:
            if position_jump or rotation_jump:
                self.jump_rejections += 1
            self.state = "recovering"
            self.reason = discontinuity_reason
            self.ready = False
            self.recovery_frames = 0
            self._filtered_position = None

        self._last_token = token
        self._last_input_position = position
        self._last_input_rotation = rotation
        self._last_input_monotonic_ns = input_ns or now_ns

        if not self.ready:
            self.state = "recovering"
            if discontinuity_reason is None:
                self.reason = "stabilizing_tracking"
            self.recovery_frames += 1
            if self.recovery_frames < self.recovery_frames_required:
                self._last_output_target = None
                return self._result(
                    target=None,
                    age_ms=age_ms,
                    position_step_m=position_step_m,
                    position_speed_m_s=position_speed_m_s,
                    rotation_step_rad=rotation_step_rad,
                )
            self.ready = True
            self.state = "ready"
            self.reason = "reanchored"
            self._filtered_position = position.copy()
            self._last_output_target = replace(target, position=position.copy())
            return self._result(
                target=self._last_output_target,
                age_ms=age_ms,
                reanchored=True,
                position_step_m=position_step_m,
                position_speed_m_s=position_speed_m_s,
                rotation_step_rad=rotation_step_rad,
            )

        previous = self._filtered_position or position
        dt_s = (
            0.0
            if input_gap_ms is None
            else max(0.0, min(input_gap_ms / 1000.0, self.max_input_gap_ms / 1000.0))
        )
        delta = [position[index] - previous[index] for index in range(3)]
        delta_norm = math.sqrt(sum(value * value for value in delta))
        if delta_norm <= self.position_deadband_m:
            filtered = previous.copy()
        else:
            alpha = 1.0 - math.exp(-dt_s / self.position_filter_tau_s) if dt_s > 0 else 1.0
            candidate = [previous[index] + alpha * delta[index] for index in range(3)]
            candidate_delta = [candidate[index] - previous[index] for index in range(3)]
            candidate_norm = math.sqrt(sum(value * value for value in candidate_delta))
            max_step = self.max_output_speed_m_s * dt_s
            scale = (
                1.0
                if candidate_norm <= max_step or candidate_norm <= 1e-12
                else max_step / candidate_norm
            )
            filtered = [previous[index] + candidate_delta[index] * scale for index in range(3)]
        self.state = "ready"
        self.reason = "tracking_ready"
        self._filtered_position = filtered
        metadata = {
            **target.source_metadata,
            "guard_input_position": position,
            "guard_filtered_position": filtered,
        }
        self._last_output_target = replace(
            target,
            position=filtered,
            source_metadata=metadata,
        )
        return self._result(
            target=self._last_output_target,
            age_ms=age_ms,
            position_step_m=position_step_m,
            position_speed_m_s=position_speed_m_s,
            rotation_step_rad=rotation_step_rad,
        )
