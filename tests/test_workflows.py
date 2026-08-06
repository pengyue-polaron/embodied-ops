from __future__ import annotations

import io
import hashlib
from pathlib import PurePath
import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from embodied_ops import (
    CollectionResetPolicy,
    EpisodeDecision,
    EvaluationPlan,
    LeadingStillnessConfig,
    LeadingStillnessTrimmer,
    OutputDirectoryTransaction,
    PublishedOutputCleanupError,
    STANDARD_COLLECTION_INTERACTION,
    TaskSelectionCancelled,
    add_contract_digest,
    atomic_output_directory,
    atomic_output_file,
    create_only_output_file,
    fetch_huggingface_artifact,
    normalize_collection_start,
    normalize_episode_decision,
    require_fresh_sample,
    require_pair_skew,
    reset_required_after_episode,
    select_task,
    summarize_evaluation_progress,
    validate_exact_metadata,
    validate_artifact,
    verify_code_checkout,
    verify_code_environment,
    load_task_catalog,
    register_task_prompt,
    validate_experiment_name,
    write_json_once,
)
from embodied_ops.console import LiveStatusLine, label


def _temporary_outputs(parent):
    return sorted(path for path in parent.iterdir() if ".staging-" in path.name)


def test_console_has_stable_machine_readable_levels_and_run_status(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    output = io.StringIO()
    assert label("pass", stream=output) == "[PASS]"
    status = LiveStatusLine(
        stream=output,
        redirected_interval_s=5.0,
        monotonic=iter((0.0, 1.0, 6.0)).__next__,
    )
    status.update("starting")
    status.update("hidden by throttle")
    status.update("ready")
    assert output.getvalue().splitlines() == ["[RUN] starting", "[RUN] ready"]


def test_collection_reset_policy_has_one_cross_robot_lifecycle_contract() -> None:
    policy = CollectionResetPolicy(
        before_collection=True,
        after_save=True,
        after_discard=False,
    )

    assert policy.before_collection is True
    assert policy.required_after(EpisodeDecision.SAVE) is True
    assert policy.required_after(EpisodeDecision.DISCARD) is False
    assert policy.required_after(EpisodeDecision.QUIT) is False


def test_leading_stillness_trimmer_emits_preroll_after_sustained_motion() -> None:
    trimmer = LeadingStillnessTrimmer[str](
        LeadingStillnessConfig(
            enabled=True,
            action_thresholds=(0.5, 0.1),
            reference_frames=2,
            motion_frames=2,
            preroll_frames=1,
        )
    )

    assert trimmer.push("reference-0", (0.0, 0.0)) == ()
    assert trimmer.push("reference-1", (0.1, 0.0)) == ()
    assert trimmer.push("still", (0.2, 0.0)) == ()
    assert trimmer.push("noise", (0.56, 0.0)) == ()
    assert trimmer.push("still-again", (0.2, 0.0)) == ()
    assert trimmer.push("motion-0", (0.7, 0.0)) == ()
    assert trimmer.push("motion-1", (0.8, 0.0)) == (
        "still-again",
        "motion-0",
        "motion-1",
    )
    assert trimmer.push("running", (0.9, 0.0)) == ("running",)
    assert trimmer.result.started is True
    assert trimmer.result.seen_frames == 8
    assert trimmer.result.emitted_frames == 4
    assert trimmer.result.trimmed_frames == 4


def test_leading_stillness_trimmer_rejects_action_contract_drift() -> None:
    trimmer = LeadingStillnessTrimmer[object](
        LeadingStillnessConfig(
            enabled=True,
            action_thresholds=(0.1,),
            reference_frames=1,
            motion_frames=1,
            preroll_frames=0,
        )
    )

    with pytest.raises(ValueError, match="action length"):
        trimmer.push(object(), (0.0, 1.0))


def test_contract_digest_and_exact_validation_are_canonical() -> None:
    expected = add_contract_digest({"protocol": "demo-v1", "shape": [2, 3]})
    assert len(expected["contract_sha256"]) == 64
    validate_exact_metadata(dict(expected), expected, label="demo")
    with pytest.raises(RuntimeError, match="shape"):
        validate_exact_metadata({**expected, "shape": [3, 2]}, expected, label="demo")


def test_verified_artifact_store_reuses_identical_local_files(tmp_path, monkeypatch) -> None:
    payload = b"portable model artifact\n"
    digest = hashlib.sha256(payload).hexdigest()
    cache_root = tmp_path / "cache"
    cached = cache_root / "another-model" / "weights.bin"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(payload)
    root = tmp_path / "models" / "target"
    config = SimpleNamespace(
        artifact_root=root,
        source=SimpleNamespace(
            provider="huggingface",
            repo_id="owner/model",
            revision="a" * 40,
        ),
        manifest=SimpleNamespace(
            files=(
                SimpleNamespace(
                    path=PurePath("weights.bin"),
                    size=len(payload),
                    sha256=digest,
                ),
            ),
            sha256="b" * 64,
        ),
    )

    def reject_download(**_kwargs) -> None:
        raise AssertionError("identical local artifact should avoid a download")

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=reject_download),
    )
    result = fetch_huggingface_artifact(config, cache_root=cache_root)

    assert result.root == root
    assert result.files == 1
    assert (root / "weights.bin").read_bytes() == payload
    assert validate_artifact(config, verify_hashes=True) == result


def _git(checkout, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=checkout,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def test_code_environment_verifies_checkout_lock_and_python(tmp_path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    _git(checkout, "config", "user.name", "Test")
    _git(checkout, "config", "user.email", "test@example.com")
    (checkout / "source.py").write_text("VALUE = 1\n")
    _git(checkout, "add", "source.py")
    _git(checkout, "commit", "-q", "-m", "test")
    repository = "https://example.com/owner/backend.git"
    _git(checkout, "remote", "add", "origin", repository)
    lock = tmp_path / "requirements.lock"
    lock.write_text("example==1\n")
    python = tmp_path / "environment/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    config = SimpleNamespace(
        source=SimpleNamespace(
            repository=repository,
            revision=_git(checkout, "rev-parse", "HEAD"),
            checkout=checkout,
        ),
        environment=SimpleNamespace(
            manager="requirements-lock",
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
            python=python,
            lock=lock,
            lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        ),
    )

    verify_code_checkout(config)
    verify_code_environment(config)
    lock.write_text("example==2\n")
    with pytest.raises(ValueError, match="lock SHA256 mismatch"):
        verify_code_checkout(config)


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


def test_directory_transaction_reports_cleanup_failure_as_published(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import embodied_ops.artifacts as artifacts

    target = tmp_path / "dataset"
    target.mkdir()
    (target / "old.txt").write_text("old")
    original_remove = artifacts._remove

    def fail_backup_cleanup(path):
        if ".backup-" in path.name:
            raise PermissionError("injected backup cleanup failure")
        original_remove(path)

    monkeypatch.setattr(artifacts, "_remove", fail_backup_cleanup)
    with OutputDirectoryTransaction(target, overwrite=True) as transaction:
        assert transaction.path is not None
        (transaction.path / "new.txt").write_text("new")
        with pytest.raises(PublishedOutputCleanupError, match="published output") as error:
            transaction.commit()
        assert transaction.committed is True

    assert error.value.target == target
    assert (target / "new.txt").read_text() == "new"
    assert not (target / "old.txt").exists()
    assert (error.value.backup / "old.txt").read_text() == "old"


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
    assert normalize_episode_decision("save") is EpisodeDecision.SAVE
    assert normalize_episode_decision("discard") is EpisodeDecision.DISCARD
    assert normalize_episode_decision("q") is EpisodeDecision.QUIT
    with pytest.raises(ValueError, match="unknown episode decision"):
        normalize_episode_decision("dscard")
    assert reset_required_after_episode(
        EpisodeDecision.DISCARD,
        after_save=False,
        after_discard=True,
    )
    assert normalize_collection_start("") is EpisodeDecision.SAVE
    assert normalize_collection_start("q") is EpisodeDecision.QUIT
    with pytest.raises(ValueError, match="only while an episode is recording"):
        normalize_collection_start("d")
    assert STANDARD_COLLECTION_INTERACTION.start_action_ids == ("enter", "quit")
    assert STANDARD_COLLECTION_INTERACTION.recording_action_ids == (
        "enter",
        "discard",
        "quit",
    )
    assert "Enter=start recording" in STANDARD_COLLECTION_INTERACTION.start_prompt(3)
    assert "Enter=save" in STANDARD_COLLECTION_INTERACTION.recording_notice(3)


def test_task_registry_loads_in_order_and_registers_create_only(tmp_path) -> None:
    root = tmp_path
    directory = root / "configs/tasks/fruit"
    prompts = directory / "prompts"
    prompts.mkdir(parents=True)
    (directory / "catalog.json").write_text('{"schema_version":1,"id":"fruit-placement"}\n')
    (prompts / "banana_bowl.json").write_text(
        '{"schema_version":1,"order":20,"id":"banana_bowl",'
        '"prompt":"put the banana in the bowl","distribution":"train"}\n'
    )
    (prompts / "apple_bowl.json").write_text(
        '{"schema_version":1,"order":10,"id":"apple_bowl",'
        '"prompt":"put the apple in the bowl","distribution":"ood"}\n'
    )

    catalog = load_task_catalog(directory / "catalog.json", repo_root=root)

    assert catalog.catalog_id == "fruit-placement"
    assert [task.task_id for task in catalog.tasks] == ["apple_bowl", "banana_bowl"]
    assert catalog.default.task_id == "apple_bowl"
    assert catalog.task("banana_bowl").distribution == "train"
    created = register_task_prompt(
        directory / "catalog.json",
        task_id="pear_bowl",
        prompt="put the pear in the bowl",
        distribution="ood",
        repo_root=root,
    )
    assert created.name == "pear_bowl.json"
    assert (
        load_task_catalog(directory / "catalog.json", repo_root=root).task("pear_bowl").prompt
        == "put the pear in the bowl"
    )
    with pytest.raises(FileExistsError, match="already registered"):
        register_task_prompt(
            directory / "catalog.json",
            task_id="pear_bowl",
            prompt="another prompt",
            distribution="ood",
            repo_root=root,
        )


def test_task_registry_rejects_paths_and_duplicate_prompt_text(tmp_path) -> None:
    root = tmp_path
    directory = root / "configs/tasks/fruit"
    prompts = directory / "prompts"
    prompts.mkdir(parents=True)
    catalog_path = directory / "catalog.json"
    catalog_path.write_text('{"schema_version":1,"id":"fruit"}\n')
    (prompts / "apple.json").write_text(
        '{"schema_version":1,"order":10,"id":"apple",'
        '"prompt":"pick the apple","distribution":"train"}\n'
    )
    outside = root / "catalog.json"
    outside.write_text('{"schema_version":1,"id":"outside"}\n')

    with pytest.raises(ValueError, match="under configs/tasks"):
        load_task_catalog(outside, repo_root=root)
    with pytest.raises(ValueError, match="already registered"):
        register_task_prompt(
            catalog_path,
            task_id="other",
            prompt="pick the apple",
            distribution="ood",
            repo_root=root,
        )


def test_task_selection_has_one_standard_number_id_prompt_and_cancel_flow(tmp_path) -> None:
    root = tmp_path
    directory = root / "configs/tasks/fruit"
    prompts = directory / "prompts"
    prompts.mkdir(parents=True)
    (directory / "catalog.json").write_text('{"schema_version":1,"id":"fruit-placement"}\n')
    (prompts / "apple.json").write_text(
        '{"schema_version":1,"order":10,"id":"apple",'
        '"prompt":"pick the apple","distribution":"train"}\n'
    )
    catalog = load_task_catalog(directory / "catalog.json", repo_root=root)

    for answer in ("1", "apple", "pick the apple"):
        output = io.StringIO()
        assert (
            select_task(catalog, input_fn=lambda value=answer: value, output=output).task_id
            == "apple"
        )
        assert "without starting model or hardware" in output.getvalue()
    with pytest.raises(TaskSelectionCancelled, match="cancelled"):
        select_task(catalog, input_fn=lambda: "q", output=io.StringIO())


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
        "task_id": "lemon_bowl",
        "task_position": 2,
        "task_count": 2,
        "attempt": 2,
        "attempt_count": 3,
        "sequence": 5,
        "total": 6,
    }
    progress = summarize_evaluation_progress(plan, (1, 2, 2, 5))
    assert progress.completed_sequences == (1, 2, 5)
    assert progress.duplicate_sequences == (2,)
    assert progress.completed_count == 3
    assert progress.pending_count == 3

    with pytest.raises(ValueError, match="unique"):
        EvaluationPlan("bad-plan", ("same", "same"), 1)
    with pytest.raises(ValueError, match="positive"):
        EvaluationPlan("bad-plan", ("task",), True)
