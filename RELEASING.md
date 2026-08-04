# Releasing

PyPI publication is driven only by a published GitHub Release. A version bump
or a commit whose message contains `Release` does not publish a package.

1. Update `CHANGELOG.md`, `pyproject.toml`, `src/embodied_ops/_version.py`, and
   `uv.lock` to the same version.
2. Run `uv sync --all-extras --dev`, `uv run pytest`, `uv run ruff check .`,
   `uv run ruff format --check .`, `uv build`, and `uvx twine check dist/*`.
3. Commit and push the exact release source to `main`.
4. Create the immutable tag `v<version>` at that commit and publish a GitHub
   Release from the tag.
5. The `publish` workflow verifies the tag against project metadata, builds the
   distributions, checks their metadata, and publishes through the `pypi`
   environment using PyPI Trusted Publishing.
6. Verify the workflow provenance and install the exact version from PyPI in a
   clean environment.

The PyPI Trusted Publisher must match repository `pengyue-polaron/embodied-ops`,
workflow `publish.yml`, and environment `pypi`. Never reuse a version or upload
new files to an existing release.
