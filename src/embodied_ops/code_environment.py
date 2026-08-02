"""Pinned source checkout and locked Python environment workflows."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Literal, Protocol


EnvironmentManager = Literal["requirements-lock", "uv-lock"]


class CodeSource(Protocol):
    repository: str
    revision: str
    checkout: Path


class PythonEnvironment(Protocol):
    manager: EnvironmentManager
    python_version: str
    python: Path
    lock: Path
    lock_sha256: str


class CodeEnvironmentConfig(Protocol):
    source: CodeSource
    environment: PythonEnvironment


def ensure_code_checkout(config: CodeEnvironmentConfig) -> None:
    checkout = config.source.checkout
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                config.source.repository,
                str(checkout),
            ]
        )
        _run(["git", "checkout", "--detach", config.source.revision], cwd=checkout)
    verify_code_checkout(config)


def verify_code_checkout(config: CodeEnvironmentConfig) -> None:
    checkout = config.source.checkout
    if not (checkout / ".git").is_dir():
        raise FileNotFoundError(f"code checkout is missing: {checkout}")
    repository = _output(["git", "remote", "get-url", "origin"], cwd=checkout)
    if repository != config.source.repository:
        raise ValueError(
            f"code checkout origin mismatch: expected {config.source.repository}, got {repository}"
        )
    revision = _output(["git", "rev-parse", "HEAD"], cwd=checkout)
    if revision != config.source.revision:
        raise ValueError(
            f"code checkout revision mismatch: expected {config.source.revision}, got {revision}"
        )
    dirty = _output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=checkout)
    if dirty:
        raise ValueError(f"code checkout has tracked modifications: {checkout}")
    verify_environment_lock(config)


def verify_environment_lock(config: CodeEnvironmentConfig) -> None:
    lock = config.environment.lock
    if not lock.is_file():
        raise FileNotFoundError(f"Python environment lock is missing: {lock}")
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    if digest != config.environment.lock_sha256:
        raise ValueError(
            "Python environment lock SHA256 mismatch: expected "
            f"{config.environment.lock_sha256}, got {digest}"
        )


def ensure_code_environment(config: CodeEnvironmentConfig) -> None:
    verify_code_checkout(config)
    environment = config.environment
    if environment.manager == "requirements-lock":
        if not environment.python.is_file():
            environment.python.parent.parent.mkdir(parents=True, exist_ok=True)
            _run(
                [
                    "uv",
                    "venv",
                    "--python",
                    environment.python_version,
                    str(environment.python.parent.parent),
                ]
            )
        _run(
            [
                "uv",
                "pip",
                "sync",
                "--python",
                str(environment.python),
                "--index-strategy",
                "unsafe-best-match",
                str(environment.lock),
            ],
            env={**os.environ, "UV_HTTP_TIMEOUT": "300"},
        )
        _run(["uv", "pip", "check", "--python", str(environment.python)])
        verify_code_environment(config)
        return
    project_environment = environment.python.parent.parent
    _run(
        [
            "uv",
            "sync",
            "--frozen",
            "--no-dev",
            "--project",
            str(config.source.checkout),
            "--python",
            environment.python_version,
        ],
        env={
            **os.environ,
            "UV_PROJECT_ENVIRONMENT": str(project_environment),
            "UV_HTTP_TIMEOUT": "300",
        },
    )
    verify_code_environment(config)


def verify_code_environment(config: CodeEnvironmentConfig) -> None:
    verify_code_checkout(config)
    python = config.environment.python
    if not python.is_file():
        raise FileNotFoundError(f"environment Python is missing: {python}")
    version = _output(
        [
            str(python),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ]
    )
    if version != config.environment.python_version:
        raise ValueError(
            "environment Python version mismatch: expected "
            f"{config.environment.python_version}, got {version}"
        )


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _output(command: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
