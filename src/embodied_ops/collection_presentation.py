"""Shared collection-session wording for terminal and Web logs."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .collection import EpisodeDecision
from .console import info, success


@dataclass(frozen=True, slots=True)
class EpisodeCaptureReport:
    episode_index: int
    sampled_frames: int
    stored_frames: int
    trimmed_frames: int
    elapsed_s: float
    effective_fps: float
    decision: EpisodeDecision

    def __post_init__(self) -> None:
        for name in ("episode_index", "sampled_frames", "stored_frames", "trimmed_frames"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.stored_frames + self.trimmed_frames != self.sampled_frames:
            raise ValueError("stored and trimmed frames must equal sampled frames")
        for name in ("elapsed_s", "effective_fps"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not isinstance(self.decision, EpisodeDecision):
            raise TypeError("decision must be an EpisodeDecision")


def announce_collection_session(
    *,
    experiment: str,
    task: str,
    repo_id: str,
    dataset_root: str,
    next_episode: int,
    configuration: str,
) -> None:
    info(f"Collection session · experiment={experiment} · task={task}")
    info(f"Dataset · repo_id={repo_id} · root={dataset_root}")
    info(f"Configuration · {configuration}")
    info(f"Next episode · index={next_episode}")


def announce_episode_capture(report: EpisodeCaptureReport) -> None:
    info(
        f"Episode {report.episode_index} capture · sampled={report.sampled_frames} "
        f"· stored={report.stored_frames} · trimmed={report.trimmed_frames} "
        f"· elapsed={report.elapsed_s:.2f}s · rate={report.effective_fps:.2f} FPS "
        f"· decision={report.decision.value}"
    )


def announce_episode_outcome(
    *,
    episode_index: int,
    decision: EpisodeDecision,
    frame_count: int,
    dataset_root: str | None,
) -> None:
    if decision is EpisodeDecision.SAVE:
        if dataset_root is None:
            raise ValueError("saved episode requires a dataset root")
        success(f"Episode {episode_index} saved · frames={frame_count} · root={dataset_root}")
        return
    info(f"Episode {episode_index} {decision.value} · frames={frame_count} · staging removed")


def announce_collection_summary(*, saved: int, discarded: int, saved_frames: int) -> None:
    info(
        f"Collection stopped · saved={saved} · discarded={discarded} · saved_frames={saved_frames}"
    )
