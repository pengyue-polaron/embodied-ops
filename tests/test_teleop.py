from __future__ import annotations

import time

import pytest

from embodied_ops.teleop import (
    TARGET_SCHEMA,
    TeleopCommand,
    TeleopFeedback,
    TeleopTarget,
    build_axis_map,
    matrix_to_quat_xyzw,
)


def target(seq: int = 1) -> TeleopTarget:
    return TeleopTarget(
        seq=seq,
        timestamp=10.0,
        position=[0.1, 0.2, 0.3],
        rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        gripper=-1.0,
        gate_open=True,
        source="unit",
        session_id="session-1",
        frame_id=seq,
        host_received_monotonic_ns=100,
        host_published_unix_ns=200,
        source_metadata={"controller_id": "right", "calibration_sha256": "abc"},
    )


def feedback(frame_index: int = 1) -> TeleopFeedback:
    return TeleopFeedback(
        backend="unit",
        episode_id="episode-1",
        frame_index=frame_index,
        status="running",
        target_seq=frame_index,
        target_age_ms=3.0,
        gate_open=True,
        recording=False,
        eef_position=[0.1, 0.2, 0.3],
        gripper=-1.0,
        action=[0.0] * 7,
    )


def test_target_round_trip_keeps_source_metadata() -> None:
    decoded = TeleopTarget.from_json(target().to_json())
    assert decoded.schema_version == TARGET_SCHEMA
    assert decoded.controller_id == "right"
    assert decoded.calibration_sha256 == "abc"


def test_target_decoder_rejects_noncanonical_schema() -> None:
    with pytest.raises(ValueError, match="unsupported teleop target schema"):
        TeleopTarget.from_dict(
            {
                "schema_version": "quest.teleop_target/v2",
                "seq": 2,
                "timestamp": 12.0,
                "position": [1, 2, 3],
                "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "gripper": 1,
                "gate_open": False,
            }
        )


def test_contracts_reject_nonfinite_control_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        TeleopTarget(
            seq=1,
            timestamp=1.0,
            position=[float("nan"), 0.0, 0.0],
            rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            gripper=0.0,
            gate_open=False,
        )


def test_geometry_helpers_are_source_neutral() -> None:
    assert build_axis_map("+y", "+x", "+z") == [
        [0.0, 1.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    assert matrix_to_quat_xyzw([[1, 0, 0], [0, 1, 0], [0, 0, 1]]) == [
        0.0,
        0.0,
        0.0,
        1.0,
    ]


def test_zmq_target_feedback_and_acknowledged_command() -> None:
    zmq = pytest.importorskip("zmq")
    from embodied_ops.teleop.zmq_transport import (
        TeleopCommandClient,
        TeleopCommandServer,
        TeleopFeedbackPublisher,
        TeleopFeedbackReceiver,
        TeleopTargetPublisher,
        TeleopTargetSubscriber,
    )

    context = zmq.Context()
    target_endpoint = "inproc://embodied-target"
    feedback_endpoint = "inproc://embodied-feedback"
    command_endpoint = "inproc://embodied-command"
    target_subscriber = TeleopTargetSubscriber(context, target_endpoint)
    target_publisher = TeleopTargetPublisher(context, target_endpoint)
    feedback_receiver = TeleopFeedbackReceiver(context, feedback_endpoint)
    feedback_publisher = TeleopFeedbackPublisher(context, feedback_endpoint)
    command_server = TeleopCommandServer(context, command_endpoint)
    command_client = TeleopCommandClient(context, command_endpoint, identity="test-ui")
    try:
        time.sleep(0.02)
        assert target_publisher.publish(target(4))
        latest_target = None
        deadline = time.monotonic() + 1.0
        while latest_target is None and time.monotonic() < deadline:
            latest_target = target_subscriber.poll(0)
            time.sleep(0.002)
        assert latest_target is not None and latest_target.seq == 4

        assert feedback_publisher.publish(feedback(5), b"agent", b"wrist")
        latest_feedback = None
        while latest_feedback is None and time.monotonic() < deadline:
            latest_feedback = feedback_receiver.newest()
            time.sleep(0.002)
        assert latest_feedback is not None
        assert latest_feedback[0].frame_index == 5
        assert latest_feedback[1:] == (b"agent", b"wrist")

        command = TeleopCommand(command="hold", request_id="request-1")
        command_client.send(command)
        requests = []
        while not requests and time.monotonic() < deadline:
            requests = command_server.take_all()
            time.sleep(0.002)
        assert len(requests) == 1
        command_server.reply(
            requests[0],
            backend="unit",
            accepted=True,
            applied=True,
            message="held",
        )
        result = command_client.receive(1000)
        assert result.applied is True
        assert result.backend == "unit"

        command_client.send(command)
        assert command_server.take_all() == []
        duplicate = command_client.receive(1000)
        assert duplicate.duplicate is True
        assert duplicate.request_id == command.request_id
    finally:
        command_client.close()
        command_server.close()
        feedback_publisher.close()
        feedback_receiver.close()
        target_publisher.close()
        target_subscriber.close()
        context.term()


def test_command_client_skips_a_late_acknowledgement() -> None:
    zmq = pytest.importorskip("zmq")
    from embodied_ops.teleop.zmq_transport import (
        TeleopCommandClient,
        TeleopCommandServer,
    )

    context = zmq.Context()
    endpoint = "inproc://embodied-late-command"
    server = TeleopCommandServer(context, endpoint)
    client = TeleopCommandClient(context, endpoint, identity="late-ui")

    def accept_one() -> None:
        deadline = time.monotonic() + 1.0
        requests = []
        while not requests and time.monotonic() < deadline:
            requests = server.take_all()
            time.sleep(0.002)
        assert len(requests) == 1
        server.reply(
            requests[0],
            backend="unit",
            accepted=True,
            applied=True,
        )

    try:
        time.sleep(0.02)
        old = TeleopCommand(command="hold", request_id="old")
        current = TeleopCommand(command="resume", request_id="current")
        client.send(old)
        accept_one()
        client.send(current)
        accept_one()

        result = client.request(current, timeout_ms=1000)

        assert result.request_id == "current"
        assert result.applied is True
    finally:
        client.close()
        server.close()
        context.term()


def test_command_server_drops_malformed_requests_without_crashing() -> None:
    zmq = pytest.importorskip("zmq")
    from embodied_ops.teleop.zmq_transport import (
        DEFAULT_COMMAND_TOPIC,
        TeleopCommandClient,
        TeleopCommandServer,
    )

    context = zmq.Context()
    endpoint = "inproc://embodied-invalid-command"
    server = TeleopCommandServer(context, endpoint)
    client = TeleopCommandClient(context, endpoint, identity="invalid-ui")
    try:
        time.sleep(0.02)
        client.socket.send_multipart([DEFAULT_COMMAND_TOPIC, b"not-json"])
        deadline = time.monotonic() + 1.0
        while server.invalid_requests == 0 and time.monotonic() < deadline:
            assert server.take_all() == []
            time.sleep(0.002)
        assert server.invalid_requests == 1
    finally:
        client.close()
        server.close()
        context.term()
