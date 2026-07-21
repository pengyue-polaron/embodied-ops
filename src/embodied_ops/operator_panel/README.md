# Operator Panel core

This package is repository-agnostic. It owns only HTTP serving, static assets,
exclusive subprocess supervision, progress presentation, guarded terminal input,
format-driven create-only document storage, and adapter-defined structured
registration forms. It has no Galaxea, ROS, camera, model, or tracked-config
imports.

A consuming repository implements `PanelAdapter` to provide its catalog,
capabilities, and argv-only workflow launches. The base adapter requires only
`repo_root`, `catalog()`, `build_launch()`, and a `PanelCapabilities` value.
Camera health, configuration documents, and structured registration are
independent providers and may be absent. Child processes call
`embodied_ops.operator_panel.announce_input()` immediately before an interactive
prompt; the panel will accept one input and lock the buttons until the next
announcement. Long-running work may call `announce_progress()` with a stable id,
label, current value, optional total, phase, and concise detail. The supervisor
keeps only the latest value for each id, so progress refreshes do not pollute the
durable terminal history. These events are presentation-only and cannot grant
input or launch work.

Consumers implement the `PanelAdapter` methods and pass the adapter to
`serve_operator_panel(adapter, bind=..., port=...)`. Workflow forms,
select options, cameras, configuration kinds, document format metadata, and
registration forms come from the adapter's JSON catalog. The core only routes
JSON values to the selected provider and blocks mutation while a workflow owns
the panel; it does not know what a registered record means. Camera presentation
stays read-only: the camera provider supplies normalized freshness, frame-age,
preview-rate, and error status without giving the panel direct access to a
device.

The terminal has its own bounded scroll area. It follows appended output only
while the viewer is already at the bottom, preserving their position while they
inspect older lines. Ordinary `[RUN]` status lines are similarly transient; the
latest one is shown above the terminal. Colors follow the browser's light or
dark preference.
