# Operator Panel core

This package is repository-agnostic. It owns only HTTP serving, static assets,
exclusive subprocess supervision, progress presentation, guarded terminal input,
format-driven create-only document storage, and adapter-defined structured
registration forms. It has no Galaxea, ROS, camera, model, or tracked-config
imports.

A consuming repository implements `PanelAdapter` to provide its catalog,
capabilities, and argv-only workflow launches. The base adapter requires only
`repo_root`, `catalog()`, `build_launch()`, and a `PanelCapabilities` value.
Every catalog uses `schema_version: 1` and is validated against the exact public
top-level, workflow, field, camera, and configuration-group contract before the
server starts and before it is returned. The public `option()`, `select_field()`,
`text_field()`, `combobox_field()`, and `checkbox_field()` builders keep forms
structurally consistent while adapters retain robot-specific values.
Camera health, configuration documents, and structured registration are
independent providers and may be absent. Child processes call
`embodied_ops.operator_panel.announce_input()` immediately before an interactive
prompt, including a semantic `phase` and concise `detail`; the panel will accept
one input and lock the buttons until the next announcement. Every input request
must echo the exact current `run_id` and `input_revision`, so stale, replayed,
or cross-run clicks are rejected. Long-running work may call
`announce_progress()` with a stable id,
label, current value, optional total, phase, and concise detail. The supervisor
keeps only the latest value for each id, so progress refreshes do not pollute the
durable terminal history. These events are presentation-only and cannot grant
input or launch work. Emitted event lines use the versioned
`{"schema_version": 2, "event": ...}` envelope; the parser continues to accept
schema-1 and original unversioned input/progress shapes for existing children but
rejects malformed events explicitly. Workflow status responses are independently
versioned at schema 2 and include a stable `run_id`, monotonic `revision`,
independent `input_revision`, input phase/detail, lifecycle `state`, and
start/finish timestamps so non-Web consumers can mirror them safely.

## Read-only status integration

`GET /api/status` is the public read-only status endpoint. Consumers must
validate `schema_version: 2` and treat `(run_id, revision)` as the snapshot
identity and ordering key. The lifecycle state is one of `idle`, `running`,
`waiting_for_input`, `stopping`, `stopped`, `succeeded`, or `failed`.
Progress entries use stable ids. `input_actions`, `input_phase`, and
`input_detail` describe only the exact current gate; `input_revision` changes
when a gate opens or is consumed.

The complete local response also contains the launched command and bounded
terminal history. Integrations that expose status on a wider telemetry surface
must construct a validated, allowlisted summary instead of forwarding the
response verbatim. Reported input-action ids are display-only and confer no
control authority. A native integration may send input only through the same
application boundary with the exact current `(run_id, input_revision, action)`
tuple. This package deliberately defines no ROS, Foxglove, or other robot-native
transport; each Runtime owns its mapping, access policy, and network boundary.

The supervisor owns the complete launched process group. If the panel server
shuts down while a workflow is active, it stops that group before completing
server shutdown.

Consumers implement the `PanelAdapter` methods and pass the adapter to
`serve_operator_panel(adapter, bind=..., port=...)`. Workflow forms,
select options, cameras, configuration kinds, document format metadata, and
registration forms come from the adapter's JSON catalog. The core only routes
JSON values to the selected provider and blocks mutation while a workflow owns
the panel; it does not know what a registered record means. Camera presentation
stays read-only: the camera provider supplies normalized freshness, frame-age,
preview-rate, and error status without giving the panel direct access to a
device.

When Web and a robot-native private transport must share one workflow owner,
construct `OperatorPanelApplication(adapter)` and pass it to
`serve_operator_panel_application()`. `create_operator_panel_server()` is the
lower-level lifecycle hook for an integration that already owns its server
thread. Both paths preserve the same serialized mutations and subprocess
shutdown behavior.

Workflow fields may use `type: "combobox"` with catalog-provided `options` when
an operator should be able to select an existing value or type a new one. The
submitted value remains plain text and is validated by the consuming adapter.

The terminal has its own bounded scroll area. It follows appended output only
while the viewer is already at the bottom, preserving their position while they
inspect older lines. Ordinary `[RUN]` status lines are similarly transient; the
latest one is shown above the terminal. The presentation uses one high-contrast
black-and-white theme so both Runtime adapters expose the same visual language.

The packaged presentation is built from `web/` with React, TypeScript, and
checked-in shadcn/ui components. Its deliberately monochrome, dense layout is
shared unchanged by every adapter. The Python server remains runtime
dependency-free and serves only the generated `index.html`, JavaScript, CSS,
and local font assets.

Workflow mutations and workflow start are serialized at the application
boundary, so configuration or registration publication cannot race a new
subprocess start.
