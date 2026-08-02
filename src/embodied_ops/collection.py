"""Hardware-independent collection lifecycle contracts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar

from .interaction import InputAction

EXPERIMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class EpisodeDecision(str, Enum):
    SAVE = "save"
    DISCARD = "discard"
    QUIT = "quit"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CollectionInteraction:
    """One standard episode interaction shared by terminal and Web clients."""

    input_actions: tuple[InputAction, ...]
    start_action_ids: tuple[str, ...]
    recording_action_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        action_ids = tuple(action.action_id for action in self.input_actions)
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("collection input action ids must be unique")
        for phase, available in (
            ("start", self.start_action_ids),
            ("recording", self.recording_action_ids),
        ):
            if not available or len(set(available)) != len(available):
                raise ValueError(f"collection {phase} action ids must be non-empty and unique")
            unknown = sorted(set(available) - set(action_ids))
            if unknown:
                raise ValueError(f"collection {phase} uses unknown actions: {unknown}")

    def start_prompt(self, episode_index: int) -> str:
        if (
            not isinstance(episode_index, int)
            or isinstance(episode_index, bool)
            or episode_index < 0
        ):
            raise ValueError("episode index must be a non-negative integer")
        return f"  [{episode_index}] Enter=start recording, q=quit > "

    def recording_notice(self, episode_index: int) -> str:
        if (
            not isinstance(episode_index, int)
            or isinstance(episode_index, bool)
            or episode_index < 0
        ):
            raise ValueError("episode index must be a non-negative integer")
        return f"Episode {episode_index} recording: Enter=save, d+Enter=discard, q+Enter=quit"


STANDARD_COLLECTION_INTERACTION = CollectionInteraction(
    input_actions=(
        InputAction("enter", "Start / Save", "\n", "primary"),
        InputAction("discard", "Discard", "d\n", "danger"),
        InputAction("quit", "Quit", "q\n", "quiet"),
    ),
    start_action_ids=("enter", "quit"),
    recording_action_ids=("enter", "discard", "quit"),
)


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


def normalize_collection_start(text: str | None) -> EpisodeDecision:
    """Accept only start or quit at the standard pre-episode prompt."""

    decision = normalize_episode_decision(text)
    if decision is EpisodeDecision.DISCARD:
        raise ValueError("discard is available only while an episode is recording")
    return decision


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
