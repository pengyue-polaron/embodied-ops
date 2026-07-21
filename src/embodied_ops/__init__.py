"""Public collection, evaluation, and artifact workflow contracts."""

from ._version import __version__
from .artifacts import (
    OutputDirectoryTransaction,
    atomic_output_directory,
    atomic_output_file,
    atomic_write_json,
    atomic_write_text,
    create_only_output_file,
    file_sha256,
    read_json_object,
    read_jsonl_objects,
    write_json_once,
    write_text_once,
)
from .collection import (
    EpisodeDecision,
    TimedSample,
    normalize_episode_decision,
    require_fresh_sample,
    require_pair_skew,
    reset_required_after_episode,
    validate_experiment_name,
)
from .evaluation import (
    EvaluationPlan,
    EvaluationSlot,
    validate_identifier,
)

__all__ = [
    "EpisodeDecision",
    "EvaluationPlan",
    "EvaluationSlot",
    "OutputDirectoryTransaction",
    "TimedSample",
    "__version__",
    "atomic_output_directory",
    "atomic_output_file",
    "atomic_write_json",
    "atomic_write_text",
    "create_only_output_file",
    "file_sha256",
    "normalize_episode_decision",
    "read_json_object",
    "read_jsonl_objects",
    "require_fresh_sample",
    "require_pair_skew",
    "reset_required_after_episode",
    "validate_experiment_name",
    "validate_identifier",
    "write_json_once",
    "write_text_once",
]
