<h1 align="center">embodied-ops</h1>

<p align="center">
  Reliable collection, evaluation, artifact, and operator workflows for embodied AI.
</p>

<p align="center">
  <a href="LICENSE"><img alt="Apache-2.0 License" src="https://img.shields.io/badge/License-Apache--2.0-blue.svg"></a>
</p>

`embodied-ops` contains the workflow primitives that sit above robot and policy
adapters: episode decisions, sample-timing checks, deterministic evaluation
plans, transactional artifact publication, and an adapter-driven local Operator
Panel. The package has no runtime dependencies and does not define a competing
robot API.

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
| Operator Panel | Minimal repository adapters, optional capability providers, exclusive workflow supervision, guarded input, typed progress, and format-driven document creation |

Use the native interface of the framework that owns the hardware integration,
such as LeRobot `Robot` and `Teleoperator`. ROS nodes, drivers, control leases,
safety limits, datasets, policies, and hardware process lifecycles remain in
those framework or robot-specific packages. The Operator Panel supervises only
the adapter-provided top-level workflow command.

## Operator Panel

A robot repository implements the minimal `PanelAdapter` and owns every catalog
value, command, and hardware decision. Optional camera, configuration, and
registration providers add only the features that repository supports. The
generic package serves the UI and runs one validated workflow at a time:

```python
from embodied_ops.operator_panel import serve_operator_panel

serve_operator_panel(adapter, bind="127.0.0.1", port=8765)
```

Child processes may announce guarded input and display-only progress through
`announce_input()` and `announce_progress()`. See
[`src/embodied_ops/operator_panel/README.md`](src/embodied_ops/operator_panel/README.md)
for the adapter and presentation contracts.

## Atomic artifacts

```python
from pathlib import Path
from embodied_ops import OutputDirectoryTransaction

with OutputDirectoryTransaction(Path("runs/eval-001")) as transaction:
    assert transaction.path is not None
    (transaction.path / "metrics.json").write_text("{}\n")
    transaction.commit()
```

If the body fails or exits without `commit()`, the staging directory is removed
and any previous complete output remains authoritative. Once publication succeeds,
`transaction.committed` remains true even if removal of the displaced backup fails;
that recovery state raises `PublishedOutputCleanupError` with both paths. Unfinished
staging or backup siblings block reuse until they are inspected. For single files,
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
