"""Bounded controller trails in the calibrated Right/Forward/Up frame."""

from collections import deque
import math

from foxglove.messages import (
    Color,
    LinePrimitive,
    LinePrimitiveLineType,
    Point3,
    Pose,
    Quaternion,
    SceneEntity,
    SceneUpdate,
    SpherePrimitive,
    TextPrimitive,
    Timestamp,
    Vector3,
)

from .contracts import TeleopTarget


class ControllerScene:
    def __init__(self) -> None:
        self.points = deque(maxlen=1200)
        self.key = None
        self.last_seq = None
        self.break_trail = True
        self.last_position = None

    def reset(self) -> None:
        self.points.clear()
        self.break_trail = True
        self.last_position = None

    def observe(self, target: TeleopTarget) -> None:
        key = (
            target.session_id,
            target.source_metadata.get("calibration_sha256"),
            target.source_metadata.get("calibration_revision"),
        )
        if key != self.key:
            self.reset()
            self.key = key
            self.last_seq = None
        if target.source_metadata.get("calibration_valid") is False:
            self.disconnect()
            return
        if not target.tracking_valid or not target.gate_open:
            self.break_trail = True
        if not target.tracking_valid or target.seq == self.last_seq:
            return
        self.last_seq = target.seq
        position = tuple(target.position)
        if not all(math.isfinite(v) for v in position):
            self.break_trail = True
            return
        if target.gate_open:
            if not self.break_trail and self.last_position is not None:
                self.points.append((self.last_position, position))
            self.break_trail = False
        self.last_position = position

    def disconnect(self) -> None:
        """Retain history but never join poses across an input outage."""
        self.break_trail = True
        self.last_position = None

    def message(self, timestamp_ns: int) -> SceneUpdate:
        identity = Quaternion(x=0, y=0, z=0, w=1)
        origin = Pose(position=Vector3(x=0, y=0, z=0), orientation=identity)
        lines, texts = [], []
        for label, end, rgb in (
            ("Right", (0.4, 0, 0), (1, 0.25, 0.25)),
            ("Forward", (0, 0.4, 0), (0.25, 1, 0.4)),
            ("Up", (0, 0, 0.4), (0.3, 0.6, 1)),
        ):
            color = Color(r=rgb[0], g=rgb[1], b=rgb[2], a=1)
            point = Vector3(x=end[0], y=end[1], z=end[2])
            lines.append(
                LinePrimitive(
                    type=LinePrimitiveLineType.LineList,
                    pose=origin,
                    thickness=3,
                    scale_invariant=True,
                    points=[Point3(x=0, y=0, z=0), Point3(x=end[0], y=end[1], z=end[2])],
                    color=color,
                )
            )
            texts.append(
                TextPrimitive(
                    pose=Pose(position=point, orientation=identity),
                    billboard=True,
                    font_size=16,
                    scale_invariant=True,
                    color=color,
                    text=label,
                )
            )
        trail = [Point3(x=p[0], y=p[1], z=p[2]) for pair in self.points for p in pair]
        if trail:
            lines.append(
                LinePrimitive(
                    type=LinePrimitiveLineType.LineList,
                    pose=origin,
                    thickness=2,
                    scale_invariant=True,
                    points=trail,
                    color=Color(r=0.1, g=0.85, b=0.95, a=1),
                )
            )
        spheres = []
        if self.last_position is not None:
            p = self.last_position
            spheres.append(
                SpherePrimitive(
                    pose=Pose(position=Vector3(x=p[0], y=p[1], z=p[2]), orientation=identity),
                    size=Vector3(x=0.025, y=0.025, z=0.025),
                    color=Color(r=1, g=0.8, b=0.1, a=1),
                )
            )
        return SceneUpdate(
            entities=[
                SceneEntity(
                    timestamp=Timestamp(
                        timestamp_ns // 1_000_000_000, timestamp_ns % 1_000_000_000
                    ),
                    frame_id="teleop_world",
                    id="calibrated-controller-trail",
                    lines=lines,
                    texts=texts,
                    spheres=spheres,
                )
            ]
        )
