"""Pure planning contracts for repeatable embodied evaluations."""

from __future__ import annotations

import re
from dataclasses import dataclass

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_identifier(value: str, *, label: str = "identifier") -> str:
    if not isinstance(value, str) or value in {".", ".."} or IDENTIFIER.fullmatch(value) is None:
        raise ValueError(
            f"{label} must be a portable 1-128 character identifier using "
            "letters, digits, '.', '_', or '-'"
        )
    return value


@dataclass(frozen=True, slots=True)
class EvaluationSlot:
    """One deterministic task/repetition position in an evaluation plan."""

    plan_id: str
    task_id: str
    task_position: int
    task_count: int
    attempt: int
    attempt_count: int

    def __post_init__(self) -> None:
        validate_identifier(self.plan_id, label="evaluation plan id")
        validate_identifier(self.task_id, label="evaluation task id")
        if (
            not _plain_positive_int(self.task_count)
            or not _plain_positive_int(self.task_position)
            or not 1 <= self.task_position <= self.task_count
        ):
            raise ValueError(
                f"invalid evaluation task position: {self.task_position}/{self.task_count}"
            )
        if (
            not _plain_positive_int(self.attempt_count)
            or not _plain_positive_int(self.attempt)
            or not 1 <= self.attempt <= self.attempt_count
        ):
            raise ValueError(f"invalid evaluation attempt: {self.attempt}/{self.attempt_count}")

    @property
    def sequence(self) -> int:
        return (self.task_position - 1) * self.attempt_count + self.attempt

    @property
    def total(self) -> int:
        return self.task_count * self.attempt_count

    def to_dict(self) -> dict[str, int | str]:
        return {
            "id": self.plan_id,
            "task_position": self.task_position,
            "task_count": self.task_count,
            "attempt": self.attempt,
            "attempt_count": self.attempt_count,
            "sequence": self.sequence,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True)
class EvaluationPlan:
    """Stable ordering of task IDs and repeated attempts."""

    identifier: str
    task_ids: tuple[str, ...]
    attempts_per_task: int

    def __post_init__(self) -> None:
        validate_identifier(self.identifier, label="evaluation plan id")
        if isinstance(self.task_ids, (str, bytes)):
            raise ValueError("evaluation task ids must be a non-empty sequence")
        task_ids = tuple(self.task_ids)
        object.__setattr__(self, "task_ids", task_ids)
        if not task_ids:
            raise ValueError("evaluation plan must contain at least one task")
        for task_id in task_ids:
            validate_identifier(task_id, label="evaluation task id")
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("evaluation task ids must be unique")
        if not _plain_positive_int(self.attempts_per_task):
            raise ValueError("attempts_per_task must be positive")

    @property
    def total_slots(self) -> int:
        return len(self.task_ids) * self.attempts_per_task

    def slot(self, *, task_position: int, attempt: int) -> EvaluationSlot:
        if not 1 <= task_position <= len(self.task_ids):
            raise ValueError(
                f"invalid evaluation task position: {task_position}/{len(self.task_ids)}"
            )
        return EvaluationSlot(
            plan_id=self.identifier,
            task_id=self.task_ids[task_position - 1],
            task_position=task_position,
            task_count=len(self.task_ids),
            attempt=attempt,
            attempt_count=self.attempts_per_task,
        )

    def slots(self) -> tuple[EvaluationSlot, ...]:
        return tuple(
            self.slot(task_position=task_position, attempt=attempt)
            for task_position in range(1, len(self.task_ids) + 1)
            for attempt in range(1, self.attempts_per_task + 1)
        )


def _plain_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
