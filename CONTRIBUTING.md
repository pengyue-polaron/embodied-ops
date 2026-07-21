# Contributing

Keep the core dependency-free and hardware-free. New abstractions need at least two
real collection or evaluation integrations with the same semantic contract. Robot,
policy, dataset-format, and UI adapters stay in their owning packages.

Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and
`uv build` before submitting changes.
