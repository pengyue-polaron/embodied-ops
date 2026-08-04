# Contributing

Keep the core dependency-free and hardware-free. New abstractions need at least two
real collection or evaluation integrations with the same semantic contract. Robot,
policy, and UI adapters stay in their owning packages. Shared dataset-format mechanics
may move here only after two integrations exercise the same behavior; robot schemas,
provenance, task policy, and readiness decisions must remain in their Runtime.

Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and
`uv build` before submitting changes.
