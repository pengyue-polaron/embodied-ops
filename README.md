<h1 align="center">embodied-ops</h1>

<p align="center">
  Reliable collection, evaluation, and artifact workflows for embodied AI.
</p>

<p align="center">
  <a href="LICENSE"><img alt="Apache-2.0 License" src="https://img.shields.io/badge/License-Apache--2.0-blue.svg"></a>
</p>

`embodied-ops` contains the workflow primitives that sit above robot and policy
adapters: episode decisions, sample-timing checks, deterministic evaluation
plans, and transactional artifact publication. The package has no runtime
dependencies and does not define a competing robot API.

## Install

```bash
python -m pip install embodied-ops
```

## Scope

| Area | Public contract |
| --- | --- |
| Collection | Portable experiment IDs, episode decisions, reset policy, sample freshness and pair skew |
| Evaluation | Stable task/repetition plans and deterministic run slots |
| Artifacts | Atomic file and directory publication, create-only reports, JSON helpers, and SHA-256 digests |

Use the native interface of the framework that owns the hardware integration,
such as LeRobot `Robot` and `Teleoperator`. ROS nodes, drivers, control leases,
safety limits, datasets, policies, and process supervision remain in those
framework or robot-specific packages.

## Atomic artifacts

```python
from pathlib import Path
from embodied_ops import OutputDirectoryTransaction

with OutputDirectoryTransaction(Path("runs/eval-001")) as output:
    assert output.path is not None
    (output.path / "metrics.json").write_text("{}\n")
    output.commit()
```

If the body fails or exits without `commit()`, the staging directory is removed
and any previous complete output remains authoritative. Unfinished staging or
backup siblings block reuse until they are inspected. For single files,
`create_only_output_file()` provides the same build-then-publish flow without
ever replacing an existing path.

## Evaluation plans

```python
from embodied_ops import EvaluationPlan

plan = EvaluationPlan(
    identifier="fruit-placement",
    task_ids=("apple_bowl", "mango_plate"),
    attempts_per_task=3,
)
for slot in plan.slots():
    print(slot.sequence, slot.total, slot.task_id)
```

Run metadata may persist `slot.to_dict()` and later reconstruct the same
task/repetition position without depending on directory order.

## Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```
