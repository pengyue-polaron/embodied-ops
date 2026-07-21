"""Transactional local artifact publication primitives."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4


def _absolute_path(path: Path) -> Path:
    """Make a path absolute without following its final symlink."""

    return Path(os.path.abspath(path.expanduser()))


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of one file without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _transaction_leftovers(target: Path) -> tuple[Path, ...]:
    patterns = (
        f".{target.name}.staging-*",
        f".{target.name}.backup-*",
    )
    return tuple(sorted(path for pattern in patterns for path in target.parent.glob(pattern)))


def _require_original_regular_file(
    path: Path,
    *,
    identity: tuple[int, int],
) -> None:
    try:
        current = os.lstat(path)
    except OSError as exc:
        raise RuntimeError(f"staged file was not created: {path}") from exc
    if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != identity:
        raise RuntimeError(f"staged output is not the allocated regular file: {path}")


class OutputDirectoryTransaction:
    """Publish a complete directory only after an explicit commit."""

    def __init__(
        self,
        target: Path,
        *,
        overwrite: bool = False,
        precreate_staging: bool = True,
    ) -> None:
        self.target = _absolute_path(target)
        self.overwrite = overwrite
        self.precreate_staging = precreate_staging
        self.path: Path | None = None
        self._committed = False

    def __enter__(self) -> OutputDirectoryTransaction:
        if self.path is not None:
            raise RuntimeError("output transaction instances cannot be reused")
        self.target.parent.mkdir(parents=True, exist_ok=True)
        if _exists(self.target) and not self.overwrite:
            raise FileExistsError(f"target root exists: {self.target}")
        leftovers = _transaction_leftovers(self.target)
        if leftovers:
            names = ", ".join(path.name for path in leftovers)
            raise RuntimeError(
                f"unfinished output transaction exists beside {self.target}: {names}"
            )
        self.path = Path(
            tempfile.mkdtemp(prefix=f".{self.target.name}.staging-", dir=self.target.parent)
        )
        if not self.precreate_staging:
            self.path.rmdir()
        return self

    def commit(self) -> Path:
        if self.path is None:
            raise RuntimeError("output transaction has not started")
        if self._committed:
            raise RuntimeError("output transaction was already committed")
        if not _exists(self.path):
            raise RuntimeError(f"staged directory was not created: {self.path}")
        try:
            staged_mode = os.lstat(self.path).st_mode
        except OSError as exc:
            raise RuntimeError(f"staged directory was not created: {self.path}") from exc
        if not stat.S_ISDIR(staged_mode):
            raise RuntimeError(f"staged output is not a real directory: {self.path}")
        _install_staged_directory(self.path, self.target, overwrite=self.overwrite)
        self._committed = True
        return self.target

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        if not self._committed and self.path is not None and _exists(self.path):
            _remove(self.path)


@contextmanager
def atomic_output_directory(
    target: Path,
    *,
    overwrite: bool,
    precreate_staging: bool = True,
) -> Iterator[Path]:
    """Build beside ``target`` and install it only after the body succeeds."""

    with OutputDirectoryTransaction(
        target,
        overwrite=overwrite,
        precreate_staging=precreate_staging,
    ) as transaction:
        assert transaction.path is not None
        yield transaction.path
        transaction.commit()


def _install_staged_directory(staging: Path, target: Path, *, overwrite: bool) -> None:
    if not _exists(target):
        os.replace(staging, target)
        return
    if not overwrite:
        raise FileExistsError(f"target root appeared during publication: {target}")

    backup = target.parent / f".{target.name}.backup-{uuid4().hex}"
    os.replace(target, backup)
    try:
        os.replace(staging, target)
    except BaseException:
        try:
            os.replace(backup, target)
        except BaseException as restore_error:
            raise RuntimeError(
                f"failed to install {target} and failed to restore backup {backup}"
            ) from restore_error
        raise
    _remove(backup)


@contextmanager
def atomic_output_file(target: Path) -> Iterator[Path]:
    """Write a sibling temporary file and atomically replace ``target``."""

    target = _absolute_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.staging-",
        dir=target.parent,
    )
    temporary_stat = os.fstat(descriptor)
    os.close(descriptor)
    staging = Path(temporary_name)
    try:
        yield staging
        _require_original_regular_file(
            staging,
            identity=(temporary_stat.st_dev, temporary_stat.st_ino),
        )
        os.replace(staging, target)
    except BaseException:
        if _exists(staging):
            _remove(staging)
        raise


@contextmanager
def create_only_output_file(target: Path) -> Iterator[Path]:
    """Build a sibling file and publish it without replacing an existing path."""

    target = _absolute_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.staging-",
        dir=target.parent,
    )
    temporary_stat = os.fstat(descriptor)
    os.close(descriptor)
    staging = Path(temporary_name)
    try:
        yield staging
        _require_original_regular_file(
            staging,
            identity=(temporary_stat.st_dev, temporary_stat.st_ino),
        )
        try:
            os.link(staging, target)
        except FileExistsError as exc:
            raise FileExistsError(f"refusing to replace artifact: {target}") from exc
    finally:
        if _exists(staging):
            _remove(staging)


def atomic_write_text(target: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically replace one text artifact."""

    with atomic_output_file(target) as staging:
        staging.write_text(text, encoding=encoding)


def atomic_write_json(target: Path, value: Mapping[str, Any]) -> None:
    """Atomically replace one deterministic JSON object."""

    atomic_write_text(target, json.dumps(dict(value), indent=2, sort_keys=True) + "\n")


def write_text_once(target: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Publish a complete text file without replacing an existing artifact."""

    with create_only_output_file(target) as staging:
        staging.write_text(text, encoding=encoding)


def write_json_once(target: Path, value: Mapping[str, Any]) -> None:
    """Publish one deterministic JSON object without replacement."""

    write_text_once(target, json.dumps(dict(value), indent=2, sort_keys=True) + "\n")


def read_json_object(path: Path) -> dict[str, Any]:
    """Read one JSON object and reject every other top-level value."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file containing objects only."""

    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not all(isinstance(item, dict) for item in values):
        raise ValueError(f"expected JSON objects: {path}")
    return values
