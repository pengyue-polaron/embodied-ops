from __future__ import annotations

import json

from embodied_ops import (
    CheckResult,
    EpisodeCaptureReport,
    EpisodeDecision,
    announce_collection_session,
    announce_collection_summary,
    announce_episode_capture,
    announce_episode_outcome,
    directory_sha256,
    finish_checks,
    print_dataset_report,
    print_export_report,
    standard_dataset_report,
    standard_export_report,
)


def test_checks_have_one_human_and_json_contract(capsys, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    checks = (
        CheckResult("camera", "PASS", "ready"),
        CheckResult("service", "WARN", "already active"),
    )

    assert finish_checks(checks, json_output=False) == 0
    assert capsys.readouterr().out.splitlines() == [
        "[PASS] camera   ready",
        "[WARN] service  already active",
    ]
    assert finish_checks(checks, json_output=True) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"detail": "ready", "level": "PASS", "name": "camera"},
        {"detail": "already active", "level": "WARN", "name": "service"},
    ]


def test_dataset_and_export_reports_share_stable_envelopes(capfd, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    dataset = standard_dataset_report(
        robot="test-arm",
        experiment="blocks_v1",
        root="/data/blocks_v1",
        repo_id="example/blocks-v1",
        episodes=3,
        frames=90,
        tasks=("place the block",),
    )
    print_dataset_report(dataset, json_output=True)
    assert json.loads(capfd.readouterr().out) == dataset

    export = standard_export_report(
        robot="test-arm",
        experiment="blocks_v1",
        result={
            "format": "v2.1",
            "episodes": 3,
            "frames": 90,
            "videos": 6,
            "camera_keys": ["observation.images.front"],
            "repo_id": "example/blocks-v1-v21",
            "root": "/data/blocks_v1_v21",
            "sha256": "a" * 64,
            "archive": "/data/blocks_v1_v21.tar.gz",
            "archive_sha256": "b" * 64,
        },
    )
    print_export_report(export, json_output=False)
    output = capfd.readouterr().out
    assert "[PASS] LeRobot v2.1 export complete" in output
    assert "experiment=blocks_v1 · episodes=3 · frames=90 · videos=6" in output
    assert "sha256=" + "a" * 64 in output


def test_collection_presentation_has_one_compact_vocabulary(capfd, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    announce_collection_session(
        experiment="blocks_v1",
        task="place the block",
        repo_id="example/blocks-v1",
        dataset_root="/data/blocks_v1",
        next_episode=2,
        configuration="sides=right · cameras=front,wrist",
    )
    capture = EpisodeCaptureReport(
        episode_index=2,
        sampled_frames=100,
        stored_frames=80,
        trimmed_frames=20,
        elapsed_s=3.4,
        effective_fps=29.4,
        decision=EpisodeDecision.SAVE,
    )
    announce_episode_capture(capture)
    announce_episode_outcome(
        episode_index=2,
        decision=EpisodeDecision.SAVE,
        frame_count=80,
        dataset_root="/data/blocks_v1",
    )
    announce_collection_summary(saved=1, discarded=0, saved_frames=80)

    output = capfd.readouterr().out
    assert "[INFO] Collection session · experiment=blocks_v1 · task=place the block" in output
    assert "[INFO] Episode 2 capture · sampled=100 · stored=80 · trimmed=20" in output
    assert "[PASS] Episode 2 saved · frames=80 · root=/data/blocks_v1" in output
    assert "[INFO] Collection stopped · saved=1 · discarded=0 · saved_frames=80" in output


def test_directory_digest_is_path_and_content_stable(tmp_path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "nested/b.txt").write_text("b")

    first = directory_sha256(tmp_path)
    assert directory_sha256(tmp_path) == first
    assert (
        directory_sha256(
            tmp_path, exclude={tmp_path.joinpath("nested/b.txt").relative_to(tmp_path)}
        )
        != first
    )
