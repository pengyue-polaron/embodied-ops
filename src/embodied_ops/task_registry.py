"""Create-only JSON task and prompt registries."""

from __future__ import annotations

import fcntl
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from .artifacts import create_only_output_file

CATALOG_SCHEMA_VERSION = 1
PROMPT_SCHEMA_VERSION = 1
TaskDistribution = Literal["train", "ood"]
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class TaskPrompt:
    task_id: str
    prompt: str
    distribution: TaskDistribution


@dataclass(frozen=True)
class TaskCatalog:
    path: Path
    catalog_id: str
    tasks: tuple[TaskPrompt, ...]

    @property
    def default(self) -> TaskPrompt:
        return self.tasks[0]

    def task(self, task_id: str) -> TaskPrompt:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        allowed = ", ".join(item.task_id for item in self.tasks)
        raise ValueError(f"unknown task id {task_id!r}; expected one of: {allowed}")

    def protocol_contract(self) -> dict[str, Any]:
        return {
            "id": self.catalog_id,
            "tasks": [
                {
                    "id": task.task_id,
                    "prompt": task.prompt,
                    "distribution": task.distribution,
                }
                for task in self.tasks
            ],
        }


def load_task_catalog(path: Path, *, repo_root: Path | None = None) -> TaskCatalog:
    """Load one strict catalog and its ordered create-only prompt records."""

    catalog_path = _catalog_path(path, repo_root=repo_root)
    payload = _load_json_object(catalog_path, label="task catalog")
    _require_exact_keys(payload, {"schema_version", "id"}, label="task catalog")
    if _integer(payload, "schema_version") != CATALOG_SCHEMA_VERSION:
        raise ValueError(f"task catalog schema_version must be {CATALOG_SCHEMA_VERSION}")
    catalog_id = _identifier(payload.get("id"), label="task catalog id")

    prompt_directory = catalog_path.parent / "prompts"
    if not prompt_directory.is_dir() or prompt_directory.is_symlink():
        raise ValueError("task catalog requires a real prompts directory")
    entries = sorted(
        entry for entry in prompt_directory.iterdir() if not entry.name.startswith(".")
    )
    invalid = [
        entry.name
        for entry in entries
        if entry.is_symlink() or not entry.is_file() or entry.suffix != ".json"
    ]
    if invalid:
        raise ValueError(f"task catalog prompt directory contains unsupported entries: {invalid}")
    if not entries:
        raise ValueError("task catalog requires at least one prompt JSON file")

    ordered = [_load_prompt(entry) for entry in entries]
    orders = [order for order, _task in ordered]
    tasks = [task for _order, task in ordered]
    if len(orders) != len(set(orders)):
        raise ValueError("task catalog prompt orders must be unique")
    if len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError("task catalog task ids must be unique")
    if len({task.prompt for task in tasks}) != len(tasks):
        raise ValueError("task catalog prompts must be unique")
    ordered.sort(key=lambda item: (item[0], item[1].task_id))
    return TaskCatalog(
        path=catalog_path,
        catalog_id=catalog_id,
        tasks=tuple(task for _order, task in ordered),
    )


def register_task_prompt(
    catalog_path: Path,
    *,
    task_id: str,
    prompt: str,
    distribution: str,
    repo_root: Path | None = None,
) -> Path:
    """Atomically create one prompt without replacing existing registry data."""

    catalog_path = _catalog_path(catalog_path, repo_root=repo_root)
    candidate = _parse_prompt(
        {
            "schema_version": PROMPT_SCHEMA_VERSION,
            "order": 0,
            "id": task_id,
            "prompt": prompt,
            "distribution": distribution,
        },
        label="new prompt",
    )[1]
    with catalog_path.open("rb") as catalog_handle:
        fcntl.flock(catalog_handle.fileno(), fcntl.LOCK_EX)
        catalog = load_task_catalog(catalog_path, repo_root=repo_root)
        if any(task.task_id == candidate.task_id for task in catalog.tasks):
            raise FileExistsError(f"task id is already registered: {candidate.task_id!r}")
        if any(task.prompt == candidate.prompt for task in catalog.tasks):
            raise ValueError(f"prompt is already registered: {candidate.prompt!r}")

        prompt_directory = catalog_path.parent / "prompts"
        current_orders = [_load_prompt(path)[0] for path in _prompt_paths(prompt_directory)]
        order = max(current_orders, default=0) + 10
        payload = {
            "schema_version": PROMPT_SCHEMA_VERSION,
            "order": order,
            "id": candidate.task_id,
            "prompt": candidate.prompt,
            "distribution": candidate.distribution,
        }
        target = prompt_directory / f"{candidate.task_id}.json"
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"prompt file already exists: {target.name}")
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        with create_only_output_file(target) as staging:
            staging.write_text(serialized, encoding="utf-8")
            _load_prompt(staging, require_matching_filename=False)

        registered = load_task_catalog(catalog_path, repo_root=repo_root).task(candidate.task_id)
        if registered != candidate:
            raise RuntimeError("registered prompt does not match the validated candidate")
        return target


def _load_prompt(path: Path, *, require_matching_filename: bool = True) -> tuple[int, TaskPrompt]:
    order, task = _parse_prompt(
        _load_json_object(path, label=f"prompt {path.name}"),
        label=f"prompt {path.name}",
    )
    if require_matching_filename and path.name != f"{task.task_id}.json":
        raise ValueError(
            f"prompt filename must match its task id: {path.name!r} != {task.task_id}.json"
        )
    return order, task


def _parse_prompt(payload: dict[str, Any], *, label: str) -> tuple[int, TaskPrompt]:
    _require_exact_keys(
        payload,
        {"schema_version", "order", "id", "prompt", "distribution"},
        label=label,
    )
    if _integer(payload, "schema_version") != PROMPT_SCHEMA_VERSION:
        raise ValueError(f"{label} schema_version must be {PROMPT_SCHEMA_VERSION}")
    order = _integer(payload, "order")
    if order < 0:
        raise ValueError(f"{label} order must be non-negative")
    task_id = _identifier(payload.get("id"), label=f"{label} id")
    prompt = payload.get("prompt")
    if (
        not isinstance(prompt, str)
        or not prompt
        or prompt != prompt.strip()
        or "\n" in prompt
        or "\r" in prompt
    ):
        raise ValueError(
            f"{label} prompt must be non-empty single-line text without surrounding whitespace"
        )
    distribution = payload.get("distribution")
    if distribution not in {"train", "ood"}:
        raise ValueError(f"{label} distribution must be train or ood")
    return order, TaskPrompt(
        task_id=task_id,
        prompt=prompt,
        distribution=cast(TaskDistribution, distribution),
    )


def _catalog_path(path: Path, *, repo_root: Path | None) -> Path:
    path = path.expanduser()
    if not path.is_absolute() and repo_root is not None:
        path = repo_root / path
    candidate = Path(os.path.abspath(os.fspath(path)))
    if repo_root is not None:
        root = repo_root.resolve()
        allowed = root / "configs/tasks"
        if not candidate.is_relative_to(allowed):
            raise ValueError("task catalog must be a repository file under configs/tasks")
        current = root
        for component in candidate.relative_to(root).parts:
            current /= component
            if current.is_symlink():
                raise ValueError("task catalog path must not contain symbolic links")
    if candidate.name != "catalog.json" or not candidate.is_file():
        raise ValueError("task catalog must reference an existing catalog.json")
    return candidate


def _identifier(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(
            f"{label} must start with a lowercase letter or digit and use only "
            "lowercase letters, digits, '-' or '_'"
        )
    return value


def _integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate key: {key!r}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _require_exact_keys(payload: dict[str, Any], expected: set[str], *, label: str) -> None:
    missing = sorted(expected - set(payload))
    unknown = sorted(set(payload) - expected)
    if missing or unknown:
        raise ValueError(f"{label} keys differ: missing={missing} unknown={unknown}")


def _prompt_paths(directory: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in directory.iterdir()
            if not path.name.startswith(".") and path.is_file() and path.suffix == ".json"
        )
    )
