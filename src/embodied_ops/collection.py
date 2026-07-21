"""Hardware-independent collection lifecycle contracts."""

from __future__ import annotations

import math
import re
from enum import Enum
from typing import Protocol, TypeVar

EXPERIMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class EpisodeDecision(str, Enum):
    SAVE = "save"
    DISCARD = "discard"
    QUIT = "quit"

    def __str__(self) -> str:
        return self.value


def reset_required_after_episode(
    decision: EpisodeDecision | str,
    *,
    after_save: bool,
    after_discard: bool,
) -> bool:
    """Return the configured reset policy for a completed episode decision."""

    if not isinstance(after_save, bool) or not isinstance(after_discard, bool):
        raise TypeError("episode reset policy values must be booleans")
    normalized = EpisodeDecision(decision)
    if normalized is EpisodeDecision.SAVE:
        return after_save
    if normalized is EpisodeDecision.DISCARD:
        return after_discard
    return False


def validate_experiment_name(value: str) -> str:
    """Validate a portable one-component collection identity."""

    if (
        not isinstance(value, str)
        or value in {".", ".."}
        or EXPERIMENT_NAME.fullmatch(value) is None
    ):
        raise ValueError(
            "experiment must be 1-128 characters using letters, digits, '.', '_', "
            "or '-', must start with a letter/digit, and cannot be '.' or '..'"
        )
    return value


def normalize_episode_decision(text: str | None) -> EpisodeDecision:
    """Map the conventional interactive collection commands to one decision."""

    value = (text or "").strip().lower()
    if value in {"", "s", "save"}:
        return EpisodeDecision.SAVE
    if value in {"d", "discard"}:
        return EpisodeDecision.DISCARD
    if value in {"q", "quit", "exit"}:
        return EpisodeDecision.QUIT
    raise ValueError(f"unknown episode decision: {text!r}")


class TimedSample(Protocol):
    seq: int
    monotonic_s: float


SampleT = TypeVar("SampleT", bound=TimedSample)


def require_fresh_sample(
    sample: SampleT | None,
    *,
    label: str,
    now_s: float,
    max_age_s: float,
) -> SampleT:
    """Return a sample only when its monotonic timestamp is valid and fresh."""

    if not math.isfinite(now_s):
        raise ValueError("now_s must be finite")
    if not math.isfinite(max_age_s) or max_age_s <= 0:
        raise ValueError("max_age_s must be finite and positive")
    if sample is None:
        raise RuntimeError(f"{label} has no sample")
    if not isinstance(sample.seq, int) or isinstance(sample.seq, bool) or sample.seq < 0:
        raise RuntimeError(f"{label} sample has an invalid sequence: {sample.seq!r}")
    if not math.isfinite(sample.monotonic_s):
        raise RuntimeError(f"{label} sample has a non-finite timestamp")
    age_s = now_s - sample.monotonic_s
    if age_s < 0:
        raise RuntimeError(f"{label} sample timestamp is in the future")
    if age_s > max_age_s:
        raise RuntimeError(
            f"{label} sample is stale: age={age_s:.3f}s, max={max_age_s:.3f}s, seq={sample.seq}"
        )
    return sample


def require_pair_skew(
    left: TimedSample,
    right: TimedSample,
    *,
    left_label: str,
    right_label: str,
    max_skew_s: float,
) -> None:
    """Reject a pair whose source timestamps are too far apart."""

    if not math.isfinite(max_skew_s) or max_skew_s < 0:
        raise ValueError("max_skew_s must be finite and non-negative")
    for sample, label in ((left, left_label), (right, right_label)):
        if not isinstance(sample.seq, int) or isinstance(sample.seq, bool) or sample.seq < 0:
            raise RuntimeError(f"{label} sample has an invalid sequence: {sample.seq!r}")
        if not math.isfinite(sample.monotonic_s):
            raise RuntimeError(f"{label} sample has a non-finite timestamp")
    skew_s = abs(left.monotonic_s - right.monotonic_s)
    if skew_s > max_skew_s:
        raise RuntimeError(
            f"{left_label}/{right_label} pair is not synchronized: "
            f"skew={skew_s:.3f}s, max={max_skew_s:.3f}s, "
            f"{left_label}_seq={left.seq}, {right_label}_seq={right.seq}"
        )
