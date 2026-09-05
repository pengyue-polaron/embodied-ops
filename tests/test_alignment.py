from dataclasses import replace
import threading

import zmq

from embodied_ops.teleop import TeleopTarget
from embodied_ops.teleop.safety import CartesianTargetGuard
from embodied_ops.teleop.recording import TeleopEpisodeProvenance
from embodied_ops.teleop.source_control import request_alignment
from embodied_ops.teleop.foxglove_bridge import diagnostic_array


def target(revision, valid=True):
    return TeleopTarget(
        seq=1,
        timestamp=1.0,
        position=[0.0, 0.0, 0.0],
        rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        gripper=-1.0,
        gate_open=True,
        source="quest",
        session_id="s",
        frame_id=1,
        tracking_valid=True,
        source_metadata={"calibration_valid": valid, "alignment": {"revision": revision}},
    )


def test_unconfirmed_calibration_never_reaches_mapper_even_if_gate_open():
    guard = CartesianTargetGuard(recovery_frames=1)
    result = guard.update(target("a", False))
    assert not result.ready and result.target is None
    assert result.reason == "calibration_required"


def test_dropped_invalid_packet_still_reanchors_on_revision_change():
    guard = CartesianTargetGuard(recovery_frames=1)
    assert guard.update(target("a")).ready
    assert guard.update(replace(target("a"), seq=2)).reason == "tracking_ready"
    result = guard.update(replace(target("b"), seq=3))
    assert result.reanchored and result.ready


def test_mixed_alignment_recording_is_preserved_but_not_training_eligible():
    provenance = TeleopEpisodeProvenance()
    provenance.observe(target("a"))
    provenance.observe(target("b"))
    assert "mixed_alignment" in provenance.eligibility_issues()
    assert len(provenance.to_dict()["alignments"]) == 2


def test_diagnostic_explains_alignment_instead_of_paused():
    result = diagnostic_array(
        timestamp_ns=1,
        source_status=None,
        source_age_sec=None,
        target=replace(target("a", False), gate_open=False),
        target_age_sec=0.01,
        feedback=None,
        feedback_age_sec=None,
    )
    assert result["status"][0]["message"] == "Calibration needs confirmation"


def test_source_rpc_roundtrip_and_bounded_timeout():
    address = []
    ready = threading.Event()

    def server():
        with zmq.Context() as context, context.socket(zmq.REP) as socket:
            port = socket.bind_to_random_port("tcp://127.0.0.1")
            address.append(f"tcp://127.0.0.1:{port}")
            ready.set()
            assert socket.poll(2000)
            request = socket.recv_json()
            socket.send_json({"accepted": True, "applied": True, "message": request["action"]})

    worker = threading.Thread(target=server)
    worker.start()
    assert ready.wait(2)
    assert request_alignment(address[0], b'{"action":"start"}')["applied"]
    worker.join(2)
    assert not worker.is_alive()
    assert not request_alignment(address[0], b"{}", timeout_ms=20)["applied"]
