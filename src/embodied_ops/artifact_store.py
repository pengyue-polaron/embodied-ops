"""Content-verified local storage for immutable external artifacts."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Protocol

from .artifacts import file_sha256


class ManifestFile(Protocol):
    path: PurePath
    size: int
    sha256: str


class ArtifactManifest(Protocol):
    files: tuple[ManifestFile, ...]
    sha256: str


class ArtifactSource(Protocol):
    provider: str
    repo_id: str
    revision: str


class ArtifactConfig(Protocol):
    @property
    def artifact_root(self) -> Path: ...

    manifest: ArtifactManifest
    source: ArtifactSource


@dataclass(frozen=True, slots=True)
class ArtifactValidation:
    root: Path
    files: int
    bytes: int
    manifest_sha256: str


def validate_artifact(
    config: ArtifactConfig,
    *,
    verify_hashes: bool,
    root: Path | None = None,
) -> ArtifactValidation:
    root = config.artifact_root if root is None else root
    if not root.is_dir():
        raise FileNotFoundError(f"artifact is missing: {root}")
    expected_paths = {Path(*item.path.parts) for item in config.manifest.files}
    actual_paths = {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and ".cache" not in path.relative_to(root).parts
    }
    missing = sorted(expected_paths - actual_paths)
    unexpected = sorted(actual_paths - expected_paths)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append("missing=" + ", ".join(map(str, missing)))
        if unexpected:
            details.append("unexpected=" + ", ".join(map(str, unexpected)))
        raise ValueError(f"artifact file set mismatch at {root}: {'; '.join(details)}")
    total_bytes = 0
    for expected in config.manifest.files:
        path = root.joinpath(*expected.path.parts)
        size = path.stat().st_size
        if size != expected.size:
            raise ValueError(
                f"artifact size mismatch for {expected.path}: expected {expected.size}, got {size}"
            )
        total_bytes += size
        if verify_hashes:
            digest = file_sha256(path)
            if digest != expected.sha256:
                raise ValueError(
                    f"artifact SHA256 mismatch for {expected.path}: "
                    f"expected {expected.sha256}, got {digest}"
                )
    return ArtifactValidation(
        root=root,
        files=len(config.manifest.files),
        bytes=total_bytes,
        manifest_sha256=config.manifest.sha256,
    )


def fetch_huggingface_artifact(
    config: ArtifactConfig,
    *,
    cache_root: Path,
    max_workers: int = 4,
) -> ArtifactValidation:
    """Fetch into hidden staging and publish only after exact validation."""

    root = config.artifact_root
    if root.exists():
        return validate_artifact(config, verify_hashes=True)
    staging = root.with_name(f".{root.name}.staging")
    if staging.exists():
        raise FileExistsError(
            f"artifact staging path already exists; inspect it before retrying: {staging}"
        )
    if config.source.provider != "huggingface":
        raise ValueError(f"unsupported artifact provider: {config.source.provider}")
    if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers <= 0:
        raise ValueError("artifact download max_workers must be a positive integer")
    from huggingface_hub import snapshot_download

    staging.parent.mkdir(parents=True, exist_ok=True)
    _seed_from_local_artifacts(config, staging, cache_root=cache_root.resolve())
    missing = [
        item.path.as_posix()
        for item in config.manifest.files
        if not staging.joinpath(*item.path.parts).is_file()
    ]
    if missing:
        snapshot_download(
            repo_id=config.source.repo_id,
            revision=config.source.revision,
            local_dir=staging,
            allow_patterns=missing,
            max_workers=max_workers,
        )
    result = validate_artifact(config, verify_hashes=True, root=staging)
    staging.rename(root)
    return ArtifactValidation(
        root=root,
        files=result.files,
        bytes=result.bytes,
        manifest_sha256=result.manifest_sha256,
    )


def _seed_from_local_artifacts(
    config: ArtifactConfig,
    staging: Path,
    *,
    cache_root: Path,
) -> None:
    if not cache_root.is_dir():
        return
    for expected in config.manifest.files:
        destination = staging.joinpath(*expected.path.parts)
        for candidate in cache_root.rglob(expected.path.name):
            if not candidate.is_file() or candidate.is_relative_to(staging):
                continue
            relative = candidate.relative_to(cache_root)
            if ".cache" in relative.parts or any(
                part.startswith(".") and part.endswith(".staging") for part in relative.parts
            ):
                continue
            if tuple(relative.parts[-len(expected.path.parts) :]) != expected.path.parts:
                continue
            if candidate.stat().st_size != expected.size:
                continue
            if file_sha256(candidate) != expected.sha256:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(candidate, destination)
            except OSError:
                shutil.copy2(candidate, destination)
            break
