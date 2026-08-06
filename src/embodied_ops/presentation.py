"""Stable human and machine-readable presentation for operator workflows."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .console import info, padded_label, success

_CHECK_LEVELS = frozenset({"PASS", "WARN", "FAIL"})


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    level: str
    detail: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("check name must not be empty")
        if self.level not in _CHECK_LEVELS:
            raise ValueError(f"check level must be one of {sorted(_CHECK_LEVELS)}")
        if not self.detail.strip():
            raise ValueError("check detail must not be empty")


def checks_payload(checks: Sequence[CheckResult]) -> list[dict[str, str]]:
    return [asdict(item) for item in checks]


def checks_to_json(checks: Sequence[CheckResult]) -> str:
    return json.dumps(checks_payload(checks), indent=2, sort_keys=True)


def checks_exit_code(checks: Sequence[CheckResult]) -> int:
    return 1 if any(item.level == "FAIL" for item in checks) else 0


def print_checks(checks: Sequence[CheckResult]) -> None:
    width = max((len(item.name) for item in checks), default=0)
    for item in checks:
        print(f"{padded_label(item.level)} {item.name:<{width}}  {item.detail}")


def finish_checks(checks: Sequence[CheckResult], *, json_output: bool) -> int:
    if json_output:
        print(checks_to_json(checks))
    else:
        print_checks(checks)
    return checks_exit_code(checks)


def standard_dataset_report(
    *,
    robot: str,
    experiment: str,
    root: str,
    repo_id: str,
    episodes: int,
    frames: int,
    tasks: Sequence[str],
) -> dict[str, object]:
    return {
        "status": "PASS",
        "workflow": "dataset-doctor",
        "robot": _text(robot, "robot"),
        "experiment": _text(experiment, "experiment"),
        "root": _text(root, "root"),
        "repo_id": _text(repo_id, "repo_id"),
        "episodes": _non_negative_int(episodes, "episodes"),
        "frames": _non_negative_int(frames, "frames"),
        "tasks": [_text(task, "task") for task in tasks],
    }


def standard_export_report(
    *,
    robot: str,
    experiment: str,
    result: Mapping[str, Any],
) -> dict[str, object]:
    report: dict[str, object] = {
        "status": "PASS",
        "workflow": "export-v21",
        "robot": _text(robot, "robot"),
        "experiment": _text(experiment, "experiment"),
        "format": _text(result.get("format"), "format"),
        "episodes": _non_negative_int(result.get("episodes"), "episodes"),
        "frames": _non_negative_int(result.get("frames"), "frames"),
        "videos": _non_negative_int(result.get("videos"), "videos"),
        "camera_keys": [
            _text(item, "camera key")
            for item in _sequence(result.get("camera_keys"), "camera_keys")
        ],
        "repo_id": _text(result.get("repo_id"), "repo_id"),
        "root": _text(result.get("root"), "root"),
    }
    if result.get("sha256") is not None:
        report["integrity"] = {"sha256": _hex_digest(result["sha256"], "sha256")}
    if result.get("archive") is not None:
        artifacts: dict[str, str] = {"archive": _text(result["archive"], "archive")}
        if result.get("archive_sha256") is not None:
            artifacts["archive_sha256"] = _hex_digest(result["archive_sha256"], "archive_sha256")
        report["artifacts"] = artifacts
    return report


def print_dataset_report(report: Mapping[str, object], *, json_output: bool) -> None:
    if json_output:
        _print_json(report)
        return
    success("Dataset doctor passed")
    info(
        f"Dataset · experiment={report['experiment']} · episodes={report['episodes']} "
        f"· frames={report['frames']}"
    )
    tasks = _sequence(report.get("tasks"), "tasks")
    info("Tasks · " + (" | ".join(str(task) for task in tasks) if tasks else "none"))
    info(f"Repository · repo_id={report['repo_id']} · root={report['root']}")


def print_export_report(report: Mapping[str, object], *, json_output: bool) -> None:
    if json_output:
        _print_json(report)
        return
    success("LeRobot v2.1 export complete")
    info(
        f"Dataset · experiment={report['experiment']} · episodes={report['episodes']} "
        f"· frames={report['frames']} · videos={report['videos']}"
    )
    cameras = _sequence(report.get("camera_keys"), "camera_keys")
    info("Cameras · " + (", ".join(str(camera) for camera in cameras) if cameras else "none"))
    info(f"Repository · repo_id={report['repo_id']} · root={report['root']}")
    integrity = report.get("integrity")
    if isinstance(integrity, Mapping) and integrity.get("sha256") is not None:
        info(f"Integrity · sha256={integrity['sha256']}")
    artifacts = report.get("artifacts")
    if isinstance(artifacts, Mapping) and artifacts.get("archive") is not None:
        info(f"Archive · path={artifacts['archive']}")


def _print_json(value: Mapping[str, object]) -> None:
    print(json.dumps(dict(value), indent=2, sort_keys=True))


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list or tuple")
    return value


def _hex_digest(value: object, label: str) -> str:
    digest = _text(value, label).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    return digest
