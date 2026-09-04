import json
import subprocess

from embodied_ops.teleop import TeleopCommandResult, TeleopFeedback, TeleopTarget
from foxglove.messages import PoseInFrame
from websockets.sync.client import connect

from embodied_ops.teleop.foxglove_bridge import (
    SERVICE_COMMANDS,
    CommandRouter,
    FoxgloveTeleopBridge,
    build_services,
    diagnostic_array,
    feedback_telemetry,
    foxglove_deep_link,
    open_foxglove,
    operator_state,
    pose_message,
)

EXPECTED_TOPICS = {
    "/teleop/agent_view",
    "/teleop/wrist_camera",
    "/teleop/eef_pose",
    "/teleop/desired_eef_pose",
    "/teleop/controller_target",
    "/teleop/telemetry",
    "/teleop/target",
    "/teleop/source_status",
    "/teleop/diagnostics",
    "/teleop/operator_state",
}


def test_command_services_cover_navigation_and_safety() -> None:
    def acknowledge(command):
        return TeleopCommandResult(
            request_id=command.request_id,
            command=command.command,
            accepted=True,
            applied=True,
            backend="unit",
        )

    router = CommandRouter(acknowledge)
    services = build_services(router)
    assert {service.name for service in services} == set(SERVICE_COMMANDS)
    response = router.execute("next_episode")
    assert response["accepted"] is True
    assert response["applied"] is True
    assert response["backend"] == "unit"


def test_feedback_is_flattened_for_foxglove_plots() -> None:
    feedback = TeleopFeedback(
        backend="unit",
        episode_id="episode-2",
        frame_index=4,
        status="running",
        target_seq=8,
        target_age_ms=3.5,
        gate_open=True,
        recording=False,
        eef_position=[0.1, 0.2, 0.3],
        gripper=-1.0,
        action=[0.4, 0.5],
        diagnostics={
            "force_x_N": 1.0,
            "force_y_N": 2.0,
            "force_z_N": 3.0,
            "force_norm_N": 3.741,
            "torque_x_Nm": 0.1,
            "torque_y_Nm": 0.2,
            "torque_z_Nm": 0.3,
            "torque_norm_Nm": 0.374,
            "wrench_bias_ready": True,
        },
    )
    telemetry = feedback_telemetry(feedback)
    assert telemetry["eef_z_m"] == 0.3
    assert telemetry["action_0"] == 0.4
    assert telemetry["action_2"] is None
    assert telemetry["force_z_N"] == 3.0
    assert telemetry["torque_y_Nm"] == 0.2
    assert telemetry["wrench_bias_ready"] is True


def test_pose_message_uses_foxglove_vector_position() -> None:
    message = pose_message(
        timestamp_ns=10,
        frame_id="world",
        position=[1.0, 2.0, 3.0],
        quaternion_xyzw=[0.0, 0.0, 0.0, 1.0],
    )
    assert isinstance(message, PoseInFrame)


def test_diagnostics_explain_tracking_loss_and_safe_hold() -> None:
    feedback = TeleopFeedback(
        backend="robotteambench_maniskill",
        episode_id="episode-2",
        frame_index=4,
        status="holding",
        target_seq=8,
        target_age_ms=3.5,
        gate_open=False,
        recording=False,
        eef_position=[0.1, 0.2, 0.3],
        gripper=-1.0,
        action=[0.0] * 7,
        diagnostics={
            "mapping_reason": "tracking_invalid",
            "guard_state": "holding",
            "recovery_frames": 0,
            "recovery_frames_required": 6,
            "jump_rejections": 1,
        },
    )
    message = diagnostic_array(
        timestamp_ns=123,
        source_status={
            "source": "quest",
            "state": "tracking_invalid",
            "stream_online": True,
            "tracking_valid": False,
            "gate_open": True,
            "raw_age_ms": 12.0,
            "source_metadata": {
                "adb_connected": True,
                "app_resumed": True,
                "tracking_loss_count": 2,
                "last_invalid_reason": "zero_position",
            },
        },
        source_age_sec=0.1,
        target=TeleopTarget(
            seq=8,
            timestamp=1.0,
            position=[0.4, 0.5, 0.6],
            rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            gripper=-1.0,
            gate_open=True,
            source="quest",
            session_id="test",
            frame_id=8,
            tracking_valid=False,
        ),
        target_age_sec=0.01,
        feedback=feedback,
        feedback_age_sec=0.02,
    )
    status = message["status"][0]
    assert status["name"] == "Teleop/Controller"
    assert status["level"] == 2
    assert status["message"] == "Disconnected"
    assert status["hardware_id"] == "quest-teleop"
    assert status["values"] == [
        {"key": "Controller state", "value": "Disconnected"},
        {"key": "Controller pose (m)", "value": "Unavailable"},
        {"key": "Input source", "value": "Quest · Online"},
    ]


def test_diagnostics_show_live_stream_and_controller_position() -> None:
    target = TeleopTarget(
        seq=9,
        timestamp=1.0,
        position=[0.1234, -0.2, 0.03],
        rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        gripper=-1.0,
        gate_open=True,
        source="quest",
        session_id="test",
        frame_id=9,
        tracking_valid=True,
    )
    feedback = TeleopFeedback(
        backend="unit",
        episode_id="episode",
        frame_index=1,
        status="running",
        target_seq=9,
        target_age_ms=4.0,
        gate_open=True,
        recording=False,
        eef_position=[0.0, 0.0, 0.0],
        gripper=-1.0,
        action=[0.0] * 7,
        diagnostics={"mapping_reason": "active"},
    )
    message = diagnostic_array(
        timestamp_ns=123,
        source_status={
            "source": "quest",
            "stream_online": True,
            "tracking_valid": True,
            "gate_open": True,
            "source_metadata": {"adb_connected": True, "app_resumed": True},
        },
        source_age_sec=0.1,
        target=target,
        target_age_sec=0.01,
        feedback=feedback,
        feedback_age_sec=0.01,
    )
    status = message["status"][0]
    assert status["level"] == 0
    assert status["message"] == "Streaming"
    assert status["values"][1]["value"] == "x +0.123  y -0.200  z +0.030"


def test_operator_state_summarizes_backend_and_view_latency() -> None:
    target = TeleopTarget(
        seq=9,
        timestamp=1.0,
        position=[0.1234, -0.2, 0.03],
        rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        gripper=-1.0,
        gate_open=True,
        source="quest",
        session_id="test",
        frame_id=9,
        tracking_valid=True,
    )
    feedback = TeleopFeedback(
        backend="forcevla_mujoco",
        episode_id="episode",
        frame_index=1,
        status="running",
        target_seq=9,
        target_age_ms=4.0,
        gate_open=True,
        recording=True,
        eef_position=[0.0, 0.0, 0.0],
        gripper=-1.0,
        action=[0.0] * 7,
        diagnostics={"mapping_reason": "active", "loop_hz": 19.8, "camera_age_ms": 52.0},
    )
    state = operator_state(
        timestamp_ns=123,
        source_status={
            "source": "quest",
            "stream_online": True,
            "tracking_valid": True,
            "gate_open": True,
            "source_metadata": {"adb_connected": True, "app_resumed": True},
        },
        source_age_sec=0.1,
        target=target,
        target_age_sec=0.01,
        feedback=feedback,
        feedback_age_sec=0.02,
    )
    assert state == {
        "status": "Streaming",
        "severity": "ok",
        "source": "Quest · Online",
        "quest": "Quest · Online",
        "controller": "Streaming",
        "backend": "forcevla_mujoco · 20 Hz",
        "view": "Live · 72 ms",
        "controller_position_m": [0.1234, -0.2, 0.03],
        "gate_open": True,
        "recording": True,
        "episode_id": "episode",
        "recording_phase": None,
        "active_agent": None,
        "replay_index": None,
        "replay_frame_count": None,
    }


def test_operator_state_exposes_sequential_dual_arm_phase() -> None:
    feedback = TeleopFeedback(
        backend="robotteambench_maniskill_sequential_dual_arm",
        episode_id="sorting-1",
        frame_index=12,
        status="running",
        target_seq=19,
        target_age_ms=4.0,
        gate_open=True,
        recording=True,
        eef_position=[0.0, 0.0, 0.0],
        gripper=-1.0,
        action=[0.0] * 7,
        diagnostics={
            "recording_phase": "replay_arm_1_record_arm_2",
            "active_agent": "panda-1",
            "arm1_replay_index": 8,
            "arm1_timeline_frames": 31,
        },
    )
    state = operator_state(
        timestamp_ns=123,
        source_status={
            "source": "synthetic",
            "stream_online": True,
            "tracking_valid": True,
            "gate_open": True,
        },
        source_age_sec=0.1,
        target=None,
        target_age_sec=None,
        feedback=feedback,
        feedback_age_sec=0.01,
    )
    assert state["recording_phase"] == "replay_arm_1_record_arm_2"
    assert state["active_agent"] == "panda-1"
    assert state["replay_index"] == 8
    assert state["replay_frame_count"] == 31


def test_fresh_target_proves_quest_online_when_status_heartbeat_is_dropped() -> None:
    target = TeleopTarget(
        seq=9,
        timestamp=1.0,
        position=[0.1, 0.2, 0.3],
        rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        gripper=-1.0,
        gate_open=True,
        source="quest",
        session_id="test",
        frame_id=9,
        tracking_valid=True,
    )
    feedback = TeleopFeedback(
        backend="unit",
        episode_id="episode",
        frame_index=1,
        status="running",
        target_seq=9,
        target_age_ms=4.0,
        gate_open=True,
        recording=False,
        eef_position=[0.0, 0.0, 0.0],
        gripper=-1.0,
        action=[0.0] * 7,
        diagnostics={"mapping_reason": "active"},
    )
    status = diagnostic_array(
        timestamp_ns=123,
        source_status=None,
        source_age_sec=None,
        target=target,
        target_age_sec=0.01,
        feedback=feedback,
        feedback_age_sec=0.01,
    )["status"][0]
    assert status["message"] == "Streaming"
    assert status["values"][2]["value"] == "Quest · Online"


def test_fresh_device_status_overrides_a_recent_pre_disconnect_target() -> None:
    target = TeleopTarget(
        seq=9,
        timestamp=1.0,
        position=[0.1, 0.2, 0.3],
        rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        gripper=-1.0,
        gate_open=True,
        source="quest",
        session_id="test",
        frame_id=9,
    )
    status = diagnostic_array(
        timestamp_ns=123,
        source_status={
            "source": "quest",
            "stream_online": False,
            "tracking_valid": False,
            "gate_open": True,
            "source_metadata": {"adb_connected": False, "app_resumed": False},
        },
        source_age_sec=0.01,
        target=target,
        target_age_sec=0.01,
        feedback=None,
        feedback_age_sec=None,
    )["status"][0]
    assert status["message"] == "Disconnected"
    assert status["values"][2]["value"] == "Quest · Offline"


def test_diagnostics_distinguish_paused_from_a_stale_controller_pose() -> None:
    source_status = {
        "source": "quest",
        "stream_online": True,
        "tracking_valid": True,
        "gate_open": False,
        "pause_state": "Low",
        "source_metadata": {"adb_connected": True, "app_resumed": True},
    }
    paused = diagnostic_array(
        timestamp_ns=123,
        source_status=source_status,
        source_age_sec=0.1,
        target=None,
        target_age_sec=None,
        feedback=None,
        feedback_age_sec=None,
    )["status"][0]
    assert paused["message"] == "Paused"
    assert paused["values"][0] == {"key": "Controller state", "value": "Paused"}

    paused_without_pose_stream = diagnostic_array(
        timestamp_ns=123,
        source_status={**source_status, "stream_online": False, "tracking_valid": False},
        source_age_sec=0.1,
        target=None,
        target_age_sec=None,
        feedback=None,
        feedback_age_sec=None,
    )["status"][0]
    assert paused_without_pose_stream["message"] == "Paused"
    assert paused_without_pose_stream["values"][0] == {
        "key": "Controller state",
        "value": "Paused",
    }

    stale_source = diagnostic_array(
        timestamp_ns=123,
        source_status=source_status,
        source_age_sec=3.0,
        target=None,
        target_age_sec=None,
        feedback=None,
        feedback_age_sec=None,
    )["status"][0]
    assert stale_source["message"] == "Disconnected"
    assert stale_source["values"][0]["value"] == "Disconnected"


def test_diagnostics_do_not_invent_a_b_state_before_controller_input() -> None:
    unknown = diagnostic_array(
        timestamp_ns=123,
        source_status={
            "source": "quest",
            "stream_online": False,
            "tracking_valid": False,
            "gate_open": False,
            "pause_state": None,
            "source_metadata": {"adb_connected": True, "app_resumed": True},
        },
        source_age_sec=0.1,
        target=None,
        target_age_sec=None,
        feedback=None,
        feedback_age_sec=None,
    )["status"][0]
    assert unknown["message"] == "Disconnected"
    assert unknown["values"][0]["value"] == "Disconnected"

    last_pressed = diagnostic_array(
        timestamp_ns=123,
        source_status={
            "source": "quest",
            "stream_online": False,
            "tracking_valid": False,
            "gate_open": True,
            "pause_state": "High",
            "source_metadata": {"adb_connected": True, "app_resumed": True},
        },
        source_age_sec=0.1,
        target=None,
        target_age_sec=None,
        feedback=None,
        feedback_age_sec=None,
    )["status"][0]
    assert last_pressed["message"] == "Disconnected"
    assert last_pressed["values"][0]["value"] == "Disconnected"


def test_diagnostics_mark_missing_source_as_stale() -> None:
    message = diagnostic_array(
        timestamp_ns=123,
        source_status=None,
        source_age_sec=None,
        target=None,
        target_age_sec=None,
        feedback=None,
        feedback_age_sec=None,
    )
    status = message["status"][0]
    assert status["level"] == 3
    assert status["message"] == "Disconnected"


def test_deep_link_omits_layout_until_a_backend_selects_one() -> None:
    link = foxglove_deep_link(
        websocket_url="ws://127.0.0.1:8765",
    )
    assert link.startswith("https://app.foxglove.dev/~/view?")
    assert "ds=foxglove-websocket" in link
    assert "ds.url=ws%3A%2F%2F127.0.0.1%3A8765" in link
    assert "layoutId=" not in link
    assert "openIn=web" in link


def test_deep_link_selects_the_backend_layout() -> None:
    link = foxglove_deep_link(
        websocket_url="ws://127.0.0.1:8765",
        layout_id="lay_backend",
    )
    assert "layoutId=lay_backend" in link


def test_open_foxglove_always_opens_the_exact_deep_link(monkeypatch) -> None:
    calls: list[list[str]] = []

    def run(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", run)

    assert open_foxglove("https://example.invalid/deep-link") == (
        "requested data source and layout"
    )
    assert calls == [["open", "https://example.invalid/deep-link"]]


def test_live_gateway_advertises_only_canonical_topics_and_services() -> None:
    bridge = FoxgloveTeleopBridge(
        target_endpoint="inproc://foxglove-test-target",
        feedback_endpoint="inproc://foxglove-test-feedback",
        command_endpoint="inproc://foxglove-test-command",
        host="127.0.0.1",
        port=0,
    )
    messages = {}
    try:
        with connect(
            f"ws://127.0.0.1:{bridge.port}",
            subprotocols=["foxglove.sdk.v1"],
            open_timeout=2,
        ) as websocket:
            for _ in range(8):
                message = websocket.recv(timeout=2)
                if isinstance(message, str):
                    value = json.loads(message)
                    messages[value["op"]] = value
                if {"serverInfo", "advertise", "advertiseServices"} <= messages.keys():
                    break
    finally:
        bridge.close()

    assert messages["serverInfo"]["capabilities"] == ["services"]
    assert {channel["topic"] for channel in messages["advertise"]["channels"]} == EXPECTED_TOPICS
    diagnostics_channel = next(
        channel
        for channel in messages["advertise"]["channels"]
        if channel["topic"] == "/teleop/diagnostics"
    )
    assert diagnostics_channel["schemaName"] == "diagnostic_msgs/msg/DiagnosticArray"
    assert {service["name"] for service in messages["advertiseServices"]["services"]} == set(
        SERVICE_COMMANDS
    )
