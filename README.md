<h1 align="center">embodied-ops</h1>

<p align="center">
  Hardware-independent operational workflows for embodied AI.
</p>

<p align="center">
  <a href="LICENSE"><img alt="Apache-2.0 License" src="https://img.shields.io/badge/License-Apache--2.0-blue.svg"></a>
</p>

`embodied-ops` defines the reusable operational layer that sits above robot and
policy adapters: a consistent CLI vocabulary, collection interaction, task
selection, sample-timing checks, deterministic evaluation, verified artifacts,
and an adapter-driven local Operator Panel. The core package has no mandatory
runtime dependencies and does not define a competing robot API.

## Install

```bash
python -m pip install embodied-ops

# Only when using the Hugging Face artifact provider
python -m pip install "embodied-ops[huggingface]"

# Shared LeRobot v3 validation and v3-to-v2.1 conversion
python -m pip install "embodied-ops[lerobot-dataset]"
```

## Scope

| Area | Public contract |
| --- | --- |
| CLI | Stable `INFO`/`STEP`/`PASS`/`WARN`/`FAIL` presentation, machine-readable no-color output, and live status lines |
| Collection | Standard Enter-to-Start/Save, Discard, and Quit actions; portable experiment IDs; episode decisions; sample freshness and pair skew |
| Tasks | Strict create-only JSON prompt catalogs and one number/id/exact-prompt selection flow |
| Evaluation | Stable task/repetition plans, deterministic run slots, and portable progress summaries |
| Artifacts | Atomic publication, exact manifests, verified Hugging Face retrieval, contract digests, and pinned code environments |
| Operator Panel | Versioned catalog and form schema, packaged Web presentation, minimal repository adapters, normalized camera health, exclusive workflow supervision, guarded input, typed progress, and format-driven document creation |
| Dataset interoperability | LeRobot v3 payload-graph validation and a format-only v3-to-v2.1 builder; Runtime callers supply robot task, feature, statistics, and provenance constraints |

The package owns cross-robot operational mechanics only. Robot repositories
still own hardware identities, feature semantics, provenance, readiness gates,
and physical safety. Use the native interface of the framework that owns the
hardware integration, such as LeRobot `Robot` and `Teleoperator`. ROS nodes,
drivers, control leases, safety limits, policies, and hardware process
lifecycles remain in those framework or robot-specific packages. The Operator
Panel supervises only the adapter-provided top-level workflow command.

Reusable LeRobot dataset-format mechanics live in
`embodied_ops.datasets.lerobot`, proven by the Galaxea A1 and VLAI L1 Runtime
integrations. Robot-specific dataset schema, task policy, provenance, and
collection composition remain with each Runtime. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the ownership rules and the
dependency boundary.

## Operator Panel

A robot repository implements the minimal `PanelAdapter` and owns every catalog
value, command, and hardware decision. The catalog must use the public versioned
schema; reusable field builders leave only choices, labels, and capabilities to
the adapter. Optional camera, configuration, and registration providers add
only the features that repository supports. The generic package serves the same
packaged UI and runs one validated workflow at a time:

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
