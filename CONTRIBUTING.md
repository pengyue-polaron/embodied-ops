# Contributing

Keep the core dependency-free and hardware-free. New abstractions need at least two
real integrations with the same semantic contract. Backends should live in their own
packages and register through `embodied_ops.backends`.

Run `uv run pytest`, `uv run ruff check .`, and `uv build` before submitting changes.
