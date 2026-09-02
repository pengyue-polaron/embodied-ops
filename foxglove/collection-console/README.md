# Embodied Ops Collection Console

Reusable Foxglove organization extension for guarded collection controls. A
robot Runtime supplies the workflow-status topic, five exact ROS Trigger
services, and the telemetry stale timeout in the panel state committed with its
layout. The extension contains no robot names or topic defaults.

The status topic carries a sanitized schema-2 Operator Panel snapshot in a ROS
`std_msgs/String`. Buttons are presentation gates only: the Runtime must still
validate the current workflow, phase, run id, input revision, and action before
forwarding an input to the shared Operator Panel application. The
`embodied_ops.foxglove` helpers implement that transport-independent validation.

Build with `npm ci && npm run build && npm run lint`. Consuming Runtime
repositories package this pinned extension and inject their configuration with
`embodied_ops.foxglove.collection_console_panel_config()`.
