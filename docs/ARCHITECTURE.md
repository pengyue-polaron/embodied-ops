# Architecture

`embodied-ops` is the hardware-independent operational layer shared by embodied
systems. It standardizes workflows and data mechanics that have the same
semantics across multiple robot integrations. It is not a universal robot API.

## Ownership

| Layer | `embodied-ops` owns | Robot Runtime owns |
| --- | --- | --- |
| Operator workflow | CLI presentation, collection decisions, task selection, evaluation plans, Panel schemas and supervision | Available commands, readiness gates, workflow composition and hardware decisions |
| Artifacts | Atomic publication, digests, verified provider retrieval and pinned code environments | Artifact identity, model policy, credentials and retention |
| Timing | Freshness, pair-skew and portable progress contracts | Sensor clocks, capture ownership and acceptable limits |
| Dataset interoperability | Shared format readers, validators and conversions proven by at least two integrations | Robot feature schema, task policy, provenance, collection and derivative configuration |
| Hardware | Nothing | Drivers, ROS/CAN/cameras, command leases, safety limits, calibration and reset |

Optional integrations must be isolated behind extras so importing the core
package remains dependency-free. Provider or dataset dependencies are loaded
only when the corresponding feature is used.

## Current and target scope

Version 0.6 implements the operator-workflow, artifact, timing, task,
evaluation and Operator Panel rows above. Dataset interoperability is the next
shared module: Galaxea A1 and VLAI L1 already contain independently evolved
LeRobot v3 graph validation and v3-to-v2.1 conversion implementations with the
same core semantics. That common engine belongs here; their schemas and
provenance do not.

Local robot transports are not currently a public `embodied-ops` contract.
The experimental generic RPC API released in 0.2 was removed in 0.3 before the
workflow boundary stabilized. A transport may return only after at least two
operational Runtime implementations demonstrate the same manifest, session,
lease and fail-closed semantics. Until then, robot-specific protocols stay with
their Runtime repository.

## Dependency direction

```text
embodied-ops core and optional data mechanics
  -> robot-specific workflow/data adapter
  -> framework adapters and Runtime client
  -> robot Runtime, safety and hardware owners
```

Dependencies must not point upward from a hardware or transport layer into an
application collection module merely to reuse a type or helper.
