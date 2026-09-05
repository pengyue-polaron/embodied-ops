# Source alignment

The source owns input calibration and publishes `calibration_valid` plus an
`alignment` metadata object. The shared Cartesian guard rejects an explicitly
invalid calibration even when tracking and the clutch are both enabled. A new
alignment revision re-anchors the mapper even if its invalidation packet was
lost. Consumers still own motion limits, simulation and recording policy.

Foxglove Diagnostics shows **Calibration needs confirmation**. The controls
extension exposes one compact Directions row: **Align → Finish → Collect forward
→ Finish**. The source then requires a B pause/resume cycle; aligning never
resets the scene or starts recording. The source command service is independent
of backend robot commands, proxied through `/teleop/source/align` to a local ZMQ
REP endpoint (`--source-control-endpoint`, default port 8133). No source package
is imported by the gateway.

Normal B pauses omit recording frames. Invalid calibration also omits frames.
Effective calibration and observed frame evidence remain in target metadata and
episode provenance. A take crossing alignment revisions is preserved but marked
`mixed_alignment` and is not automatically training-eligible. Save that take and
start a new recording after alignment if you need a clean training episode.

Controller trails reset on alignment revision changes so old and new coordinates
are never joined. The recovered source APK offers only best-effort frame-change
detection; this guard cannot guarantee detection of an event it was never told
about. Manual Align remains available when physical directions change.
