"""Shared LeRobot v3 validation and v3-to-v2.1 format conversion.

This module deliberately knows nothing about a robot's joint schema, task policy,
or provenance document. Runtime repositories supply those constraints through the
validator arguments and add their own metadata around the format-only v2.1 build.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from embodied_ops.artifacts import atomic_write_text

LEROBOT_GENERATED_FRAME_COLUMNS = (
    "timestamp",
    "frame_index",
    "episode_index",
    "index",
    "task_index",
)
V21_DATA_PATH = "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet"
V21_VIDEO_PATH = "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4"
V21_CHUNK_SIZE = 1000


@dataclass(frozen=True)
class LeRobotV3Summary:
    """Validated counts and task/video identities from one LeRobot v3 dataset."""

    info: dict[str, Any]
    total_episodes: int
    total_frames: int
    tasks: tuple[str, ...]
    video_keys: tuple[str, ...]


@dataclass(frozen=True)
class _VideoProbe:
    frames: int
    width: int
    height: int


def validate_lerobot_v3_dataset(
    root: Path,
    *,
    info: dict[str, Any] | None = None,
    expected_episodes: int | None = None,
    expected_frames: int | None = None,
    expected_tasks: tuple[str, ...] | None = None,
    required_frame_columns: Collection[str] = LEROBOT_GENERATED_FRAME_COLUMNS,
    required_stat_features: Collection[str] = (),
) -> LeRobotV3Summary:
    """Validate the complete metadata and referenced payload graph of a v3 dataset."""

    pd, parquet, _ = _dataset_dependencies()
    root = root.expanduser().resolve()
    info = dict(info) if info is not None else _read_json(root / "meta/info.json", "info")
    if info.get("codebase_version") != "v3.0":
        raise ValueError("LeRobot dataset must declare codebase_version v3.0")
    total_episodes = _json_non_negative_int(info, "total_episodes")
    total_frames = _json_non_negative_int(info, "total_frames")
    if expected_episodes is not None and total_episodes != expected_episodes:
        raise ValueError("LeRobot episode count differs from the Runtime provenance")
    if expected_frames is not None and total_frames != expected_frames:
        raise ValueError("LeRobot frame count differs from the Runtime provenance")

    features = info.get("features")
    if not isinstance(features, dict):
        raise ValueError("LeRobot info.features must be an object")
    stats = _read_json(root / "meta/stats.json", "stats")
    missing_stats = set(required_stat_features) - set(stats)
    if missing_stats:
        raise ValueError(f"LeRobot stats are missing {sorted(missing_stats)}")

    tasks = read_lerobot_v3_tasks(root, info=info)
    if expected_tasks is not None and tasks != expected_tasks:
        raise ValueError(
            "LeRobot task metadata differs from the Runtime provenance: "
            f"metadata={tasks!r}, provenance={expected_tasks!r}"
        )
    task_set = set(tasks)

    episode_paths = sorted((root / "meta/episodes").glob("**/*.parquet"))
    if not episode_paths:
        raise ValueError("LeRobot dataset has no episode metadata")
    episodes = pd.concat(
        [_read_parquet(pd, path, label="episode metadata") for path in episode_paths],
        ignore_index=True,
    )
    required_episode_columns = {
        "episode_index",
        "tasks",
        "length",
        "data/chunk_index",
        "data/file_index",
        "dataset_from_index",
        "dataset_to_index",
    }
    missing = required_episode_columns - set(episodes.columns)
    if missing:
        raise ValueError(f"LeRobot episode metadata is missing {sorted(missing)}")
    if len(episodes) != total_episodes:
        raise ValueError("LeRobot episode metadata count differs from info.json")
    episodes = episodes.sort_values("episode_index")
    indices = [_integer(value, "episode_index") for value in episodes["episode_index"]]
    if indices != list(range(total_episodes)):
        raise ValueError("LeRobot episode indices must be contiguous from zero")

    data_template = _path_template(info, "data_path")
    video_keys = tuple(
        key
        for key, feature in features.items()
        if isinstance(feature, dict) and feature.get("dtype") == "video"
    )
    video_template = _path_template(info, "video_path") if video_keys else None
    expected_rows: dict[Path, int] = defaultdict(int)
    used_tasks: set[str] = set()
    next_frame = 0
    for _, row in episodes.iterrows():
        episode = _integer(row["episode_index"], "episode_index")
        length = _positive_integer(row["length"], f"episode {episode} length")
        start = _non_negative_integer(row["dataset_from_index"], "dataset_from_index")
        end = _non_negative_integer(row["dataset_to_index"], "dataset_to_index")
        if start != next_frame or end != start + length:
            raise ValueError(f"episode {episode} has a non-contiguous frame range")
        next_frame = end
        row_tasks = tuple(str(task) for task in row["tasks"])
        if not row_tasks or len(set(row_tasks)) != len(row_tasks):
            raise ValueError(f"episode {episode} must reference unique registered tasks")
        if not set(row_tasks) <= task_set:
            raise ValueError(f"episode {episode} references an unknown task")
        used_tasks.update(row_tasks)
        data_path = _format_dataset_path(
            root,
            data_template,
            chunk_index=_non_negative_integer(row["data/chunk_index"], "data chunk"),
            file_index=_non_negative_integer(row["data/file_index"], "data file"),
        )
        expected_rows[data_path] += length
        for key in video_keys:
            assert video_template is not None
            chunk_column = f"videos/{key}/chunk_index"
            file_column = f"videos/{key}/file_index"
            if chunk_column not in episodes.columns or file_column not in episodes.columns:
                raise ValueError(f"episode metadata is missing video reference {key!r}")
            video_path = _format_dataset_path(
                root,
                video_template,
                video_key=key,
                chunk_index=_non_negative_integer(row[chunk_column], f"{key} video chunk"),
                file_index=_non_negative_integer(row[file_column], f"{key} video file"),
            )
            _require_regular_file(video_path, label="LeRobot video payload")
    if next_frame != total_frames:
        raise ValueError("LeRobot episode frame ranges differ from info.json")
    if used_tasks != task_set:
        raise ValueError("LeRobot task metadata contains a task with no episode")

    required_columns = set(required_frame_columns)
    for path, rows in expected_rows.items():
        _require_regular_file(path, label="LeRobot data payload")
        try:
            payload = parquet.ParquetFile(path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read LeRobot data payload {path}: {exc}") from exc
        if payload.metadata.num_rows != rows:
            raise ValueError(
                f"LeRobot data row count differs for {path}: "
                f"expected={rows}, actual={payload.metadata.num_rows}"
            )
        missing_columns = required_columns - set(payload.schema_arrow.names)
        if missing_columns:
            raise ValueError(f"LeRobot data payload is missing {sorted(missing_columns)}")
    return LeRobotV3Summary(info, total_episodes, total_frames, tasks, video_keys)


def read_lerobot_v3_tasks(root: Path, *, info: dict[str, Any]) -> tuple[str, ...]:
    """Return normalized task text in task-index order."""

    pd, _, _ = _dataset_dependencies()
    path = root.expanduser().resolve() / "meta/tasks.parquet"
    tasks = _read_parquet(pd, path, label="tasks")
    if list(tasks.columns) != ["task_index"]:
        raise ValueError("LeRobot tasks must contain exactly the task_index column")
    records = {int(row["task_index"]): str(task) for task, row in tasks.iterrows()}
    total_tasks = _json_non_negative_int(info, "total_tasks")
    if total_tasks <= 0 or sorted(records) != list(range(total_tasks)):
        raise ValueError("LeRobot task indices must be contiguous from zero")
    ordered = tuple(records[index] for index in range(total_tasks))
    if any(not task or task.strip() != task or "\n" in task or "\r" in task for task in ordered):
        raise ValueError("LeRobot tasks must be non-empty normalized single lines")
    if len(set(ordered)) != len(ordered):
        raise ValueError("LeRobot tasks must be unique")
    return ordered


def build_lerobot_v21_dataset(
    source_root: Path,
    target_root: Path,
    *,
    expected_episodes: int | None = None,
    expected_frames: int | None = None,
) -> dict[str, Any]:
    """Build format-only v2.1 files in a caller-owned staging directory.

    The caller owns transactional publication and robot-specific provenance. The
    target must be empty so a partial or ambiguous derivative cannot be accepted.
    """

    pd, parquet, np = _dataset_dependencies()
    source_root = source_root.expanduser().resolve()
    target_root = target_root.expanduser().resolve()
    if target_root.exists() and any(target_root.iterdir()):
        raise FileExistsError(f"v2.1 staging directory is not empty: {target_root}")
    target_root.mkdir(parents=True, exist_ok=True)
    summary = validate_lerobot_v3_dataset(
        source_root,
        expected_episodes=expected_episodes,
        expected_frames=expected_frames,
    )
    info = summary.info
    data_paths = sorted(source_root.glob("data/**/*.parquet"))
    episode_paths = sorted(source_root.glob("meta/episodes/**/*.parquet"))
    frames = pd.concat(
        [_read_parquet(pd, path, label="data payload") for path in data_paths],
        ignore_index=True,
    )
    episodes = pd.concat(
        [_read_parquet(pd, path, label="episode metadata") for path in episode_paths],
        ignore_index=True,
    ).sort_values("episode_index")
    tasks_frame = _read_parquet(pd, source_root / "meta/tasks.parquet", label="tasks")
    if len(frames) != summary.total_frames or len(episodes) != summary.total_episodes:
        raise ValueError("LeRobot v3 payload counts changed after source validation")

    meta_root = target_root / "meta"
    meta_root.mkdir(parents=True)
    task_records = _task_records(tasks_frame)
    _write_jsonl(meta_root / "tasks.jsonl", task_records)
    task_by_index = {record["task_index"]: record["task"] for record in task_records}
    metadata_by_episode = {int(row["episode_index"]): row for _, row in episodes.iterrows()}
    episode_records: list[dict[str, Any]] = []
    stats_records: list[dict[str, Any]] = []
    for _, metadata in episodes.iterrows():
        episode = int(metadata["episode_index"])
        episode_frames = frames[frames["episode_index"] == episode].copy()
        if episode_frames.empty:
            raise ValueError(f"v3 metadata references empty episode {episode}")
        episode_frames = episode_frames.sort_values("frame_index")
        expected = np.arange(len(episode_frames), dtype=np.int64)
        if not np.array_equal(episode_frames["frame_index"].to_numpy(), expected):
            raise ValueError(f"episode {episode} frame_index is not contiguous")
        data_path = target_root / V21_DATA_PATH.format(
            episode_chunk=episode // V21_CHUNK_SIZE,
            episode_index=episode,
        )
        data_path.parent.mkdir(parents=True, exist_ok=True)
        episode_frames.to_parquet(data_path, index=False)
        indices = sorted({int(value) for value in episode_frames["task_index"]})
        try:
            tasks = [task_by_index[index] for index in indices]
        except KeyError as exc:
            raise ValueError(f"episode {episode} references an unknown task") from exc
        episode_records.append(
            {"episode_index": episode, "tasks": tasks, "length": len(episode_frames)}
        )
        stats_records.append({"episode_index": episode, "stats": _episode_stats(metadata)})
    _write_jsonl(meta_root / "episodes.jsonl", episode_records)
    _write_jsonl(meta_root / "episodes_stats.jsonl", stats_records)

    video_count = _write_episode_videos(
        source_root=source_root,
        target_root=target_root,
        info=info,
        video_keys=list(summary.video_keys),
        episode_records=episode_records,
        metadata_by_episode=metadata_by_episode,
    )
    _write_json(meta_root / "info.json", make_lerobot_v21_info(info))
    shutil.copy2(source_root / "meta/stats.json", meta_root / "stats.json")
    training = source_root / "TRAINING.md"
    if training.is_file() and not training.is_symlink():
        shutil.copy2(training, target_root / training.name)
    _validate_v21_output(
        target_root,
        parquet=parquet,
        episodes=episode_records,
        video_keys=list(summary.video_keys),
        expected_frames=summary.total_frames,
    )
    return {
        "format": "v2.1",
        "episodes": summary.total_episodes,
        "frames": summary.total_frames,
        "videos": video_count,
        "camera_keys": list(summary.video_keys),
    }


def make_lerobot_v21_info(source: dict[str, Any]) -> dict[str, Any]:
    """Construct episode-based LeRobot v2.1 info without changing feature names."""

    features = json.loads(json.dumps(source["features"]))
    video_keys = [
        key
        for key, feature in features.items()
        if isinstance(feature, dict) and feature.get("dtype") == "video"
    ]
    for key in video_keys:
        height, width, channels = features[key]["shape"]
        features[key]["info"] = {
            "video.height": int(height),
            "video.width": int(width),
            "video.codec": "h264",
            "video.pix_fmt": "yuv420p",
            "video.is_depth_map": False,
            "video.fps": int(source["fps"]),
            "video.channels": int(channels),
            "has_audio": False,
        }
    episodes = int(source["total_episodes"])
    return {
        "codebase_version": "v2.1",
        "robot_type": source.get("robot_type"),
        "total_episodes": episodes,
        "total_frames": int(source["total_frames"]),
        "total_tasks": int(source["total_tasks"]),
        "total_videos": episodes * len(video_keys),
        "total_chunks": (episodes + V21_CHUNK_SIZE - 1) // V21_CHUNK_SIZE,
        "chunks_size": V21_CHUNK_SIZE,
        "fps": int(source["fps"]),
        "splits": {"train": f"0:{episodes}"},
        "data_path": V21_DATA_PATH,
        "video_path": V21_VIDEO_PATH if video_keys else None,
        "features": features,
    }


def _write_episode_videos(
    *,
    source_root: Path,
    target_root: Path,
    info: dict[str, Any],
    video_keys: list[str],
    episode_records: list[dict[str, Any]],
    metadata_by_episode: dict[int, Any],
) -> int:
    count = 0
    fps = int(info["fps"])
    template = _path_template(info, "video_path") if video_keys else ""
    for key in video_keys:
        for record in episode_records:
            episode = int(record["episode_index"])
            metadata = metadata_by_episode[episode]
            source = _format_dataset_path(
                source_root,
                template,
                video_key=key,
                chunk_index=int(metadata[f"videos/{key}/chunk_index"]),
                file_index=int(metadata[f"videos/{key}/file_index"]),
            )
            _require_regular_file(source, label="LeRobot video payload")
            start_frame = round(float(metadata[f"videos/{key}/from_timestamp"]) * fps)
            target = target_root / V21_VIDEO_PATH.format(
                episode_chunk=episode // V21_CHUNK_SIZE,
                video_key=key,
                episode_index=episode,
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            _slice_video(
                source=source,
                target=target,
                start_frame=start_frame,
                frame_count=int(record["length"]),
                fps=fps,
            )
            probe = _probe_video(target)
            if probe.frames != int(record["length"]):
                raise RuntimeError(
                    f"video frame mismatch for {key} episode {episode}: "
                    f"expected={record['length']}, actual={probe.frames}"
                )
            expected_height, expected_width, _ = info["features"][key]["shape"]
            if (probe.height, probe.width) != (expected_height, expected_width):
                raise RuntimeError(
                    f"video geometry mismatch for {key} episode {episode}: "
                    f"expected={expected_width}x{expected_height}, "
                    f"actual={probe.width}x{probe.height}"
                )
            count += 1
    return count


def _slice_video(
    *, source: Path, target: Path, start_frame: int, frame_count: int, fps: int
) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("LeRobot video conversion requires the ffmpeg executable")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{start_frame / fps:.9f}",
            "-i",
            str(source),
            "-frames:v",
            str(frame_count),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
    )


def _probe_video(path: Path) -> _VideoProbe:
    if shutil.which("ffprobe") is None:
        raise RuntimeError("LeRobot video validation requires the ffprobe executable")
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_frames,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams")
    if not isinstance(streams, list) or len(streams) != 1:
        raise RuntimeError(f"ffprobe returned an invalid video stream for {path}")
    try:
        stream = streams[0]
        return _VideoProbe(
            frames=int(stream["nb_frames"]),
            width=int(stream["width"]),
            height=int(stream["height"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"ffprobe returned incomplete video metadata for {path}") from exc


def _validate_v21_output(
    root: Path,
    *,
    parquet: Any,
    episodes: list[dict[str, Any]],
    video_keys: list[str],
    expected_frames: int,
) -> None:
    rows = 0
    for record in episodes:
        episode = int(record["episode_index"])
        data = root / V21_DATA_PATH.format(
            episode_chunk=episode // V21_CHUNK_SIZE,
            episode_index=episode,
        )
        rows += parquet.ParquetFile(data).metadata.num_rows
        for key in video_keys:
            video = root / V21_VIDEO_PATH.format(
                episode_chunk=episode // V21_CHUNK_SIZE,
                video_key=key,
                episode_index=episode,
            )
            _require_regular_file(video, label="LeRobot v2.1 video")
    if rows != expected_frames:
        raise ValueError("LeRobot v2.1 parquet row count differs from the v3 source")


def _task_records(frame: Any) -> list[dict[str, Any]]:
    return [
        {"task_index": int(row["task_index"]), "task": str(task)}
        for task, row in frame.sort_values("task_index").iterrows()
    ]


def _episode_stats(row: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for column, value in row.items():
        if not isinstance(column, str) or not column.startswith("stats/"):
            continue
        _, feature, statistic = column.split("/", 2)
        result.setdefault(feature, {})[statistic] = _json_value(value)
    return result


def _dataset_dependencies() -> tuple[Any, Any, Any]:
    try:
        import numpy as np
        import pandas as pd
        import pyarrow.parquet as parquet
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "LeRobot dataset operations require embodied-ops[lerobot-dataset]"
        ) from exc
    return pd, parquet, np


def _read_json(path: Path, label: str) -> dict[str, Any]:
    _require_regular_file(path, label=f"LeRobot {label}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read LeRobot {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"LeRobot {label} must be a JSON object: {path}")
    return value


def _read_parquet(pd: Any, path: Path, *, label: str) -> Any:
    _require_regular_file(path, label=f"LeRobot {label}")
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read LeRobot {label} {path}: {exc}") from exc


def _require_regular_file(path: Path, *, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is missing or unsafe: {path}")


def _path_template(info: dict[str, Any], key: str) -> str:
    value = info.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"LeRobot info.{key} must be a non-empty path template")
    return value


def _format_dataset_path(root: Path, template: str, **values: object) -> Path:
    try:
        relative = Path(template.format(**values))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid LeRobot payload path template {template!r}") from exc
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"LeRobot payload path escapes its dataset: {relative}")
    return root / relative


def _json_non_negative_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"LeRobot info.{key} must be a non-negative integer")
    return value


def _integer(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if isinstance(value, bool) or float(value) != result:
        raise ValueError(f"{label} must be an integer")
    return result


def _non_negative_integer(value: Any, label: str) -> int:
    result = _integer(value, label)
    if result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _positive_integer(value: Any, label: str) -> int:
    result = _integer(value, label)
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    atomic_write_text(
        path,
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
    )


def _json_value(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return _json_value(value.tolist())
    if hasattr(value, "item"):
        return _json_value(value.item())
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
