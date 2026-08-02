"""Canonical digests and exact metadata matching for workflow handshakes."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def add_contract_digest(contract: dict[str, Any]) -> dict[str, Any]:
    if "contract_sha256" in contract:
        raise ValueError("contract must not contain a precomputed digest")
    result = dict(contract)
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    result["contract_sha256"] = hashlib.sha256(encoded).hexdigest()
    return result


def validate_exact_metadata(
    actual: object,
    expected: dict[str, Any],
    *,
    label: str,
) -> None:
    if not isinstance(actual, dict):
        raise RuntimeError(
            f"{label} server metadata must be a dictionary, got {type(actual).__name__}"
        )
    if actual == expected:
        return
    keys = sorted(set(actual) | set(expected))
    mismatched = [key for key in keys if actual.get(key) != expected.get(key)]
    raise RuntimeError(f"{label} server contract mismatch: " + ", ".join(mismatched))
