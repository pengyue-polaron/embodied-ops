from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from embodied_ops.datasets.lerobot import (
    LEROBOT_GENERATED_FRAME_COLUMNS,
    V21_DATA_PATH,
    build_lerobot_v21_dataset,
    make_lerobot_v21_info,
    validate_lerobot_v3_dataset,
)


def _write_v3_dataset(root: Path) -> None:
    (root / "meta/episodes/chunk-000").mkdir(parents=True)
    (root / "data/chunk-000").mkdir(parents=True)
    features = {
        "observation.state": {"dtype": "float32", "shape": [2], "names": ["a", "b"]},
        "action": {"dtype": "float32", "shape": [2], "names": ["a", "b"]},
        **{
            key: {"dtype": "float32" if key == "timestamp" else "int64", "shape": [1]}
            for key in LEROBOT_GENERATED_FRAME_COLUMNS
        },
    }
    info = {
        "codebase_version": "v3.0",
        "robot_type": "fixture_robot",
        "fps": 30,
        "total_episodes": 1,
        "total_frames": 2,
        "total_tasks": 1,
        "features": features,
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": None,
    }
    (root / "meta/info.json").write_text(json.dumps(info), encoding="utf-8")
    (root / "meta/stats.json").write_text(
        json.dumps({"observation.state": {}, "action": {}}), encoding="utf-8"
    )
    pd.DataFrame({"task_index": [0]}, index=["pick the block"]).to_parquet(
        root / "meta/tasks.parquet"
    )
    pd.DataFrame(
        {
            "episode_index": [0],
            "tasks": [["pick the block"]],
            "length": [2],
            "data/chunk_index": [0],
            "data/file_index": [0],
            "dataset_from_index": [0],
            "dataset_to_index": [2],
            "stats/observation.state/min": [[0.0, 0.0]],
        }
    ).to_parquet(root / "meta/episodes/chunk-000/file-000.parquet")
    pd.DataFrame(
        {
            "timestamp": [0.0, 1 / 30],
            "frame_index": [0, 1],
            "episode_index": [0, 0],
            "index": [0, 1],
            "task_index": [0, 0],
            "observation.state": [[0.0, 0.0], [0.1, 0.2]],
            "action": [[0.1, 0.2], [0.2, 0.3]],
        }
    ).to_parquet(root / "data/chunk-000/file-000.parquet")


def test_validate_v3_graph_with_runtime_constraints(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_v3_dataset(source)

    summary = validate_lerobot_v3_dataset(
        source,
        expected_episodes=1,
        expected_frames=2,
        expected_tasks=("pick the block",),
        required_frame_columns=(*LEROBOT_GENERATED_FRAME_COLUMNS, "observation.state", "action"),
        required_stat_features=("observation.state", "action"),
    )

    assert summary.total_frames == 2
    assert summary.video_keys == ()


def test_validate_v3_rejects_task_provenance_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_v3_dataset(source)

    with pytest.raises(ValueError, match="Runtime provenance"):
        validate_lerobot_v3_dataset(source, expected_tasks=("place the block",))


def test_build_v21_writes_episode_based_parquet_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_v3_dataset(source)

    result = build_lerobot_v21_dataset(source, target)

    assert result == {
        "format": "v2.1",
        "episodes": 1,
        "frames": 2,
        "videos": 0,
        "camera_keys": [],
    }
    assert (
        len(pd.read_parquet(target / V21_DATA_PATH.format(episode_chunk=0, episode_index=0))) == 2
    )
    info = json.loads((target / "meta/info.json").read_text(encoding="utf-8"))
    assert info["codebase_version"] == "v2.1"
    assert info["video_path"] is None


def test_make_v21_info_preserves_robot_feature_names() -> None:
    source = {
        "robot_type": "fixture_robot",
        "fps": 30,
        "total_episodes": 2,
        "total_frames": 12,
        "total_tasks": 1,
        "features": {
            "observation.state": {
                "dtype": "float32",
                "shape": [2],
                "names": ["joint_a", "joint_b"],
            }
        },
    }

    result = make_lerobot_v21_info(source)

    assert result["features"]["observation.state"]["names"] == ["joint_a", "joint_b"]
