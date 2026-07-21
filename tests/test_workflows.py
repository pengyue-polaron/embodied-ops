from __future__ import annotations

from dataclasses import dataclass

import pytest

from embodied_ops import (
    EpisodeDecision,
    EvaluationPlan,
    OutputDirectoryTransaction,
    atomic_output_directory,
    atomic_output_file,
    create_only_output_file,
    normalize_episode_decision,
    require_fresh_sample,
    require_pair_skew,
    reset_required_after_episode,
    validate_experiment_name,
    write_json_once,
)


def _temporary_outputs(parent):
    return sorted(path for path in parent.iterdir() if ".staging-" in path.name)


def test_directory_transaction_preserves_previous_artifact_until_commit(tmp_path) -> None:
    target = tmp_path / "dataset"
    target.mkdir()
    (target / "old.txt").write_text("old")

    with pytest.raises(RuntimeError, match="injected"):
        with atomic_output_directory(target, overwrite=True) as staging:
            (staging / "new.txt").write_text("new")
            raise RuntimeError("injected failure")

    assert (target / "old.txt").read_text() == "old"
    assert _temporary_outputs(tmp_path) == []

    with OutputDirectoryTransaction(target, overwrite=True) as transaction:
        assert transaction.path is not None
        (transaction.path / "new.txt").write_text("new")
        transaction.commit()

    assert (target / "new.txt").read_text() == "new"
    assert not (target / "old.txt").exists()
    with pytest.raises(FileExistsError, match="target root exists"):
        with atomic_output_directory(target, overwrite=False):
            pass


def test_directory_transaction_can_defer_staging_creation(tmp_path) -> None:
    target = tmp_path / "dataset"

    with OutputDirectoryTransaction(target, precreate_staging=False) as transaction:
        assert transaction.path is not None
        assert not transaction.path.exists()
        transaction.path.mkdir()
        (transaction.path / "complete.txt").write_text("ready")
        transaction.commit()

    assert (target / "complete.txt").read_text() == "ready"


def test_directory_transaction_rejects_symlink_staging_and_crash_leftovers(
    tmp_path,
) -> None:
    target = tmp_path / "dataset"
    outside = tmp_path / "outside"
    outside.mkdir()
    with OutputDirectoryTransaction(target, precreate_staging=False) as transaction:
        assert transaction.path is not None
        transaction.path.symlink_to(outside, target_is_directory=True)
        with pytest.raises(RuntimeError, match="not a real directory"):
            transaction.commit()
    assert outside.is_dir()

    leftover = tmp_path / ".dataset.backup-crash"
    leftover.mkdir()
    with pytest.raises(RuntimeError, match="unfinished output transaction"):
        with OutputDirectoryTransaction(target):
            pass


def test_atomic_file_failure_preserves_previous_artifact(tmp_path) -> None:
    target = tmp_path / "dataset.tar"
    target.write_bytes(b"old")

    with pytest.raises(RuntimeError, match="injected"):
        with atomic_output_file(target) as staging:
            staging.write_bytes(b"new")
            raise RuntimeError("injected failure")

    assert target.read_bytes() == b"old"
    assert _temporary_outputs(tmp_path) == []


def test_create_only_json_never_replaces_a_published_artifact(tmp_path) -> None:
    target = tmp_path / "report.json"

    write_json_once(target, {"status": "complete"})

    with pytest.raises(FileExistsError, match="refusing to replace"):
        write_json_once(target, {"status": "changed"})
    assert target.read_text() == '{\n  "status": "complete"\n}\n'


def test_create_only_file_preserves_a_target_that_appears_during_build(tmp_path) -> None:
    target = tmp_path / "report.bin"

    with pytest.raises(FileExistsError, match="refusing to replace"):
        with create_only_output_file(target) as staging:
            staging.write_bytes(b"generated")
            target.write_bytes(b"racer")

    assert target.read_bytes() == b"racer"
    assert _temporary_outputs(tmp_path) == []


def test_collection_identity_and_episode_decisions_are_portable() -> None:
    assert validate_experiment_name("pick_cube.v2-01") == "pick_cube.v2-01"
    with pytest.raises(ValueError):
        validate_experiment_name("../escape")

    assert normalize_episode_decision("") is EpisodeDecision.SAVE
    assert normalize_episode_decision("discard") is EpisodeDecision.DISCARD
    assert normalize_episode_decision("q") is EpisodeDecision.QUIT
    assert reset_required_after_episode(
        EpisodeDecision.DISCARD,
        after_save=False,
        after_discard=True,
    )


@dataclass(frozen=True)
class Sample:
    seq: int
    monotonic_s: float


def test_timed_samples_enforce_freshness_and_pair_skew() -> None:
    front = require_fresh_sample(
        Sample(7, 9.8),
        label="front",
        now_s=10.0,
        max_age_s=0.5,
    )
    wrist = Sample(9, 9.75)
    require_pair_skew(
        front,
        wrist,
        left_label="front",
        right_label="wrist",
        max_skew_s=0.1,
    )

    with pytest.raises(RuntimeError, match="stale"):
        require_fresh_sample(
            Sample(8, 9.0),
            label="front",
            now_s=10.0,
            max_age_s=0.5,
        )
    with pytest.raises(RuntimeError, match="not synchronized"):
        require_pair_skew(
            front,
            Sample(10, 9.0),
            left_label="front",
            right_label="wrist",
            max_skew_s=0.1,
        )
    with pytest.raises(RuntimeError, match="non-finite timestamp"):
        require_pair_skew(
            Sample(11, float("nan")),
            wrist,
            left_label="front",
            right_label="wrist",
            max_skew_s=0.1,
        )


def test_evaluation_plan_assigns_stable_slots() -> None:
    plan = EvaluationPlan(
        identifier="fruit-placement",
        task_ids=("red_mango_bowl", "lemon_bowl"),
        attempts_per_task=3,
    )

    slots = plan.slots()

    assert plan.total_slots == 6
    assert [slot.sequence for slot in slots] == [1, 2, 3, 4, 5, 6]
    assert slots[4].task_id == "lemon_bowl"
    assert slots[4].to_dict() == {
        "id": "fruit-placement",
        "task_position": 2,
        "task_count": 2,
        "attempt": 2,
        "attempt_count": 3,
        "sequence": 5,
        "total": 6,
    }

    with pytest.raises(ValueError, match="unique"):
        EvaluationPlan("bad-plan", ("same", "same"), 1)
    with pytest.raises(ValueError, match="positive"):
        EvaluationPlan("bad-plan", ("task",), True)
