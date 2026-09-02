# Architecture

`embodied-ops` is the hardware-independent operational layer shared by embodied
systems. It standardizes workflows and data mechanics that have the same
semantics across multiple robot integrations. It is not a universal robot API.

## Ownership

| Layer | `embodied-ops` owns | Robot Runtime owns |
| --- | --- | --- |
| Operator workflow | CLI levels, check/dataset result presentation, collection decisions and summaries, task selection, evaluation plans, Panel schemas and supervision | Available commands, readiness gates, workflow composition and hardware decisions |
| Operational status | Versioned workflow snapshots, lifecycle states, run/input revisions, phase-aware guarded-input visibility, stale/replay rejection, and owned-process termination | Native telemetry mapping, field sanitization, network exposure, action allowlists, and any control transport |
| Foxglove presentation | Robot-neutral Collection Console, strict per-layout topic/service state, and organization-layout API mechanics | Native messages/services, bridge lifecycle, concrete layout, URDF/sensors, network policy, and action authorization |
| Artifacts | Atomic publication, digests, verified provider retrieval and pinned code environments | Artifact identity, model policy, credentials and retention |
| Timing | Freshness, pair-skew and portable progress contracts | Sensor clocks, capture ownership and acceptable limits |
| Cartesian teleoperation | Source-neutral target/feedback/command schemas, frame geometry, latest-state transport, idempotent command acknowledgement, and a configurable dropout/reacquisition guard | Device protocol, calibration, guard thresholds, native action mapping, workspace/physical safety policy, cameras, and recording |
| Dataset interoperability | Shared format readers, validators and conversions proven by at least two integrations | Robot feature schema, task policy, provenance, collection and derivative configuration |
| Hardware | Nothing | Drivers, ROS/CAN/cameras, command leases, safety limits, calibration and reset |

Optional integrations must be isolated behind extras so importing the core
package remains dependency-free. Provider or dataset dependencies are loaded
only when the corresponding feature is used.

## Current scope

Version 0.9 implements the operator-workflow, artifact, timing, task,
evaluation, Operator Panel, Foxglove-presentation, and dataset-interoperability
rows above. The shared
dataset module validates LeRobot v3 metadata/payload graphs and builds the
format-only portion of v2.1 derivatives. Galaxea A1 and VLAI L1 provide the
robot feature requirements, task/provenance checks, publication transaction,
and robot-specific derivative metadata around that engine.

General-purpose local robot transports are not a public `embodied-ops` contract.
The experimental generic RPC API released in 0.2 was removed in 0.3 before the
workflow boundary stabilized. The narrow Cartesian teleoperation data plane is
an exception proven by independent ManiSkill and MuJoCo backends: it exchanges
operator intent and action-aligned observation, but it does not expose a robot
driver, lease, or hardware lifecycle. A broader transport may return only after at least two
operational Runtime implementations demonstrate the same manifest, session,
lease and fail-closed semantics. Until then, robot-specific protocols stay with
their Runtime repository.

The Operator Panel's read-only status endpoint is a presentation contract, not
a robot transport. The shared Foxglove console consumes a sanitized projection
through Runtime-supplied topic and Trigger-service names stored in each layout;
it contains no robot identity or endpoint defaults. The Runtime owns the native
mapping, bridge process, allowlists, network exposure, concrete layout, and
service authorization. Every forwarded input must carry the current run id and
input-gate revision and still pass the declared action check. Command arguments
and terminal history require deliberate sanitization before wider exposure.

## Dependency direction

```text
embodied-ops core and optional data mechanics
  -> robot-specific workflow/data adapter
  -> framework adapters and Runtime client
  -> robot Runtime, safety and hardware owners
```

Dependencies must not point upward from a hardware or transport layer into an
application collection module merely to reuse a type or helper.
