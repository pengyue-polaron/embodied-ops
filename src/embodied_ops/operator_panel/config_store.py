"""Validated, create-only repository configuration storage."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


_CONFIG_NAME = re.compile(r"[a-z][a-z0-9_-]*")


def _include_all(_path: Path) -> bool:
    return True


@dataclass(frozen=True)
class ConfigKind:
    kind_id: str
    label: str
    directory: Path
    validate: Callable[[Path], None]
    include: Callable[[Path], bool] = _include_all


class RepositoryConfigStore:
    def __init__(self, repo_root: Path, kinds: tuple[ConfigKind, ...]) -> None:
        self.repo_root = repo_root.resolve()
        self._kinds = {kind.kind_id: kind for kind in kinds}
        if len(self._kinds) != len(kinds):
            raise ValueError("configuration kind ids must be unique")
        for kind in kinds:
            if kind.directory.is_absolute() or ".." in kind.directory.parts:
                raise ValueError("configuration directories must be repository-relative")

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "id": kind.kind_id,
                "label": kind.label,
                "templates": [
                    {
                        "value": path.relative_to(self.repo_root).as_posix(),
                        "label": path.stem,
                    }
                    for path in self._paths(kind)
                ],
            }
            for kind in self._kinds.values()
        ]

    def template(self, kind_id: str, source: str) -> dict[str, str]:
        kind = self._kind(kind_id)
        path = self._source(kind, source)
        kind.validate(path)
        return {
            "kind": kind.kind_id,
            "source": path.relative_to(self.repo_root).as_posix(),
            "content": path.read_text(),
        }

    def validate(self, kind_id: str, filename: str, content: str) -> dict[str, object]:
        kind = self._kind(kind_id)
        target = self._target(kind, filename)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"configuration already exists: {target.name}")
        staging = self._stage(kind, target, content)
        staging.unlink()
        return {
            "valid": True,
            "path": target.relative_to(self.repo_root).as_posix(),
        }

    def create(self, kind_id: str, filename: str, content: str) -> dict[str, str]:
        kind = self._kind(kind_id)
        target = self._target(kind, filename)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"configuration already exists: {target.name}")
        staging = self._stage(kind, target, content)
        try:
            os.link(staging, target)
        except FileExistsError as exc:
            raise FileExistsError(
                f"configuration appeared while creating it: {target.name}"
            ) from exc
        finally:
            staging.unlink(missing_ok=True)
        return {"created": target.relative_to(self.repo_root).as_posix()}

    def _kind(self, kind_id: str) -> ConfigKind:
        try:
            return self._kinds[kind_id]
        except KeyError as exc:
            raise ValueError(f"unknown configuration kind: {kind_id!r}") from exc

    def _paths(self, kind: ConfigKind) -> list[Path]:
        directory = (self.repo_root / kind.directory).resolve()
        return sorted(path.resolve() for path in directory.glob("*.toml") if kind.include(path))

    def _source(self, kind: ConfigKind, source: str) -> Path:
        if not isinstance(source, str) or not source:
            raise ValueError("configuration template path is required")
        path = (self.repo_root / source).resolve()
        directory = (self.repo_root / kind.directory).resolve()
        if not path.is_relative_to(directory) or path.suffix != ".toml":
            raise ValueError("template must belong to the selected configuration kind")
        if path not in self._paths(kind):
            raise FileNotFoundError(f"configuration template is missing: {source}")
        return path

    def _target(self, kind: ConfigKind, filename: str) -> Path:
        if not isinstance(filename, str):
            raise ValueError("configuration filename must be text")
        stem = filename.removesuffix(".toml")
        if not _CONFIG_NAME.fullmatch(stem):
            raise ValueError(
                "configuration filename must start with a lowercase letter and "
                "contain only lowercase letters, digits, underscores, or hyphens"
            )
        return (self.repo_root / kind.directory / f"{stem}.toml").resolve()

    def _stage(self, kind: ConfigKind, target: Path, content: str) -> Path:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("configuration content must not be empty")
        if "\x00" in content:
            raise ValueError("configuration content must not contain NUL bytes")
        normalized = content if content.endswith("\n") else content + "\n"
        for existing in self._paths(kind):
            if existing.read_text() == normalized:
                raise ValueError(
                    f"configuration content duplicates existing template: {existing.name}"
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staging_name = tempfile.mkstemp(
            prefix=f".{target.stem}.candidate-",
            suffix=".toml",
            dir=target.parent,
        )
        staging = Path(staging_name)
        try:
            os.fchmod(descriptor, 0o644)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(normalized)
                handle.flush()
                os.fsync(handle.fileno())
            kind.validate(staging)
        except BaseException:
            staging.unlink(missing_ok=True)
            raise
        return staging
