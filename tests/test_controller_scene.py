from dataclasses import replace

from embodied_ops.teleop import TeleopTarget
from embodied_ops.teleop.controller_scene import ControllerScene
from foxglove.channels import SceneUpdateChannel
import foxglove


def target(seq, **kwargs):
    return TeleopTarget(
        seq=seq,
        timestamp=seq / 72,
        position=[seq / 100, 0.2, 0.3],
        rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        gripper=0,
        gate_open=True,
        session_id="test",
        **kwargs,
    )


def test_axes_marker_and_native_serialization():
    scene = ControllerScene()
    scene.observe(target(1))
    scene.observe(target(2))
    message = scene.message(1_234_567_890)
    encoded = message.encode()
    for label in (b"teleop_world", b"Right", b"Forward", b"Up"):
        assert label in encoded
    assert scene.last_position == (0.02, 0.2, 0.3)
    context = foxglove.Context()
    SceneUpdateChannel("/scene-test", context=context).log(message)


def test_pause_disconnect_and_invalid_tracking_break_segments():
    scene = ControllerScene()
    scene.observe(target(1))
    scene.observe(target(2))
    scene.observe(replace(target(3), gate_open=False))
    scene.observe(target(4))
    assert len(scene.points) == 1
    scene.observe(target(5))
    scene.observe(replace(target(6), tracking_valid=False))
    scene.observe(target(7))
    assert len(scene.points) == 2
    scene.disconnect()
    assert scene.last_position is None
    scene.observe(target(8))
    assert len(scene.points) == 2


def test_reset_profile_changes_and_bounded_history():
    scene = ControllerScene()
    for i in range(1400):
        scene.observe(target(i))
    assert len(scene.points) == 1200
    scene.observe(target(1399))
    assert len(scene.points) == 1200
    scene.reset()
    assert not scene.points
    assert scene.last_position is None
    scene.observe(target(1400))
    assert not scene.points
    scene.observe(target(1401))
    assert len(scene.points) == 1
    scene.observe(target(1402, source_metadata={"calibration_sha256": "new"}))
    assert not scene.points
