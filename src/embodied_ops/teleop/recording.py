"""Durable, backend-neutral episode recording primitives."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import TeleopTarget

EPISODE_MANIFEST_SCHEMA = "embodied.teleop_episode/v1"
STEP_SCHEMA = "embodied.teleop_step/v1"


@dataclass(slots=True)
class TeleopEpisodeProvenance:
    """Summarize source identity and continuity across one recorded take."""

    target_count: int = 0
    first_target_seq: int | None = None
    last_target_seq: int | None = None
    sequence_regressions: int = 0
    sources: set[str] = field(default_factory=set)
    session_ids: set[str] = field(default_factory=set)
    controller_ids: set[str] = field(default_factory=set)
    calibration_ids: set[str] = field(default_factory=set)
    calibration_sha256: set[str] = field(default_factory=set)
    alignments: dict[str, dict[str, Any]] = field(default_factory=dict)
    _last_seq_by_session: dict[str, int] = field(default_factory=dict, repr=False)

    def observe(self, target: TeleopTarget | None) -> None:
        if target is None:
            return
        if (
            target.session_id in self._last_seq_by_session
            and target.seq < self._last_seq_by_session[target.session_id]
        ):
            self.sequence_regressions += 1
        if self.first_target_seq is None:
            self.first_target_seq = target.seq
        self.last_target_seq = target.seq
        self._last_seq_by_session[target.session_id] = target.seq
        self.target_count += 1
        self.sources.add(target.source)
        self.session_ids.add(target.session_id)
        self.controller_ids.add(target.controller_id)
        if target.calibration_id is not None:
            self.calibration_ids.add(target.calibration_id)
        if target.calibration_sha256 is not None:
            self.calibration_sha256.add(target.calibration_sha256)
        alignment = target.source_metadata.get("alignment")
        if isinstance(alignment, dict) and isinstance(alignment.get("revision"), str):
            self.alignments[alignment["revision"]] = alignment

    def eligibility_issues(self) -> list[str]:
        issues = []
        if self.target_count == 0:
            issues.append("no_source_target")
        if len(self.sources) != 1:
            issues.append("mixed_source")
        if len(self.session_ids) != 1:
            issues.append("mixed_source_session")
        if self.sequence_regressions:
            issues.append("target_sequence_regression")
        if len(self.calibration_ids) > 1 or len(self.calibration_sha256) > 1:
            issues.append("mixed_calibration")
        if len(self.alignments) > 1:
            issues.append("mixed_alignment")
        if self.sources == {"quest"} and len(self.calibration_sha256) != 1:
            issues.append("missing_quest_calibration_digest")
        return issues

    @property
    def training_eligible(self) -> bool:
        return not self.eligibility_issues()

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_count": self.target_count,
            "first_target_seq": self.first_target_seq,
            "last_target_seq": self.last_target_seq,
            "sequence_regressions": self.sequence_regressions,
            "sources": sorted(self.sources),
            "session_ids": sorted(self.session_ids),
            "controller_ids": sorted(self.controller_ids),
            "calibration_ids": sorted(self.calibration_ids),
            "calibration_sha256": sorted(self.calibration_sha256),
            "alignments": self.alignments,
            "eligibility_issues": self.eligibility_issues(),
        }


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def describe_artifact(
    path: Path,
    *,
    relative_to: Path,
    media_type: str,
    sample_count: int | None = None,
) -> dict[str, Any]:
    resolved = path.resolve()
    root = relative_to.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("artifact must be inside the episode directory") from exc
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    result: dict[str, Any] = {
        "path": relative.as_posix(),
        "media_type": media_type,
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }
    if sample_count is not None:
        if sample_count < 0:
            raise ValueError("sample_count must be non-negative")
        result["sample_count"] = int(sample_count)
    return result


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON durably and atomically; the final path is the commit marker."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_descriptor = None
        if directory_descriptor is not None:
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def build_episode_manifest(
    *,
    backend: str,
    episode_id: str,
    step_count: int,
    operator_disposition: str,
    termination_reason: str,
    training_eligible: bool,
    artifacts: dict[str, dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not backend or not episode_id or not termination_reason:
        raise ValueError("backend, episode_id, and termination_reason are required")
    if step_count < 0:
        raise ValueError("step_count must be non-negative")
    if operator_disposition not in {"saved", "interrupted"}:
        raise ValueError("operator_disposition must be saved or interrupted")
    if training_eligible and operator_disposition != "saved":
        raise ValueError("only saved recordings can be training eligible")
    normalized_artifacts: dict[str, dict[str, Any]] = {}
    for name, descriptor in artifacts.items():
        if not name or not isinstance(descriptor, dict):
            raise ValueError("artifact names must be non-empty and descriptors must be objects")
        required = {"path", "media_type", "bytes", "sha256"}
        if not required.issubset(descriptor):
            raise ValueError(f"artifact {name!r} is missing required fields")
        if (
            not isinstance(descriptor["path"], str)
            or not descriptor["path"]
            or not isinstance(descriptor["media_type"], str)
            or not descriptor["media_type"]
            or isinstance(descriptor["bytes"], bool)
            or not isinstance(descriptor["bytes"], int)
            or descriptor["bytes"] < 0
            or not isinstance(descriptor["sha256"], str)
            or len(descriptor["sha256"]) != 64
        ):
            raise ValueError(f"artifact {name!r} has an invalid descriptor")
        sample_count = descriptor.get("sample_count")
        if sample_count is not None and sample_count != step_count:
            raise ValueError(f"artifact {name!r} sample_count does not match episode step_count")
        normalized_artifacts[name] = dict(descriptor)
    return {
        "schema_version": EPISODE_MANIFEST_SCHEMA,
        "backend": backend,
        "episode_id": episode_id,
        "integrity_complete": True,
        "operator_disposition": operator_disposition,
        "training_eligible": bool(training_eligible),
        "termination_reason": termination_reason,
        "step_count": int(step_count),
        "artifacts": normalized_artifacts,
        "metadata": {} if metadata is None else dict(metadata),
    }
