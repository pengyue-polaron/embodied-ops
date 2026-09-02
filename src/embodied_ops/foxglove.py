"""Reusable Foxglove presentation and organization-layout mechanics."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from argparse import Namespace
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

from .console import ArgumentParser, success
from .operator_panel import WORKFLOW_STATUS_SCHEMA_VERSION


FOXGLOVE_LAYOUTS_API = "https://api.foxglove.dev/v1/layouts"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
COLLECTION_CONSOLE_PANEL_TYPE = "embodied-ops-collection-console.Collection Console"
COLLECTION_CONSOLE_CONFIG_SCHEMA_VERSION = 1
FOXGLOVE_WORKFLOW_STATUS_SCHEMA_VERSION = 2
COLLECTION_SERVICE_NAMES = ("start", "save", "discard", "reset", "stop")


@dataclass(frozen=True)
class PublishedLayout:
    id: str
    name: str
    action: str


@dataclass(frozen=True)
class CollectionActionRequest:
    action_id: str
    run_id: str
    input_revision: int


def collection_console_panel_config(
    *,
    status_topic: str,
    services: Mapping[str, str],
    stale_after_ms: int = 3000,
) -> dict[str, object]:
    """Build validated per-Runtime state for the shared collection console."""

    if not isinstance(status_topic, str) or not status_topic:
        raise ValueError("Foxglove workflow status topic must be a non-empty string")
    if isinstance(stale_after_ms, bool) or not isinstance(stale_after_ms, int):
        raise ValueError("Foxglove stale timeout must be an integer")
    if stale_after_ms < 500:
        raise ValueError("Foxglove stale timeout must be at least 500 ms")
    expected = set(COLLECTION_SERVICE_NAMES)
    actual = set(services)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(repr(name) for name in actual - expected)
        raise ValueError(
            "Foxglove collection services must contain exactly "
            f"{sorted(expected)}; missing={missing}, unknown={unknown}"
        )
    normalized: dict[str, str] = {}
    for name in COLLECTION_SERVICE_NAMES:
        value = services[name]
        if not isinstance(value, str) or not value:
            raise ValueError(f"Foxglove collection service {name!r} must be a non-empty string")
        normalized[name] = value
    if len(set(normalized.values())) != len(normalized):
        raise ValueError("Foxglove collection service names must be unique")
    return {
        "schemaVersion": COLLECTION_CONSOLE_CONFIG_SCHEMA_VERSION,
        "statusTopic": status_topic,
        "services": normalized,
        "staleAfterMs": stale_after_ms,
    }


def foxglove_workflow_status(
    snapshot: object | None,
    *,
    error: str = "",
) -> dict[str, object]:
    """Validate and sanitize an Operator Panel snapshot for wider telemetry."""

    if snapshot is None:
        return {
            "schema_version": FOXGLOVE_WORKFLOW_STATUS_SCHEMA_VERSION,
            "available": False,
            "error": error or "Operator Panel unavailable",
        }
    if not isinstance(snapshot, dict):
        raise ValueError("Operator Panel status must be a JSON object")
    if snapshot.get("schema_version") != WORKFLOW_STATUS_SCHEMA_VERSION:
        raise ValueError("Operator Panel status schema version mismatch")
    revision = snapshot.get("revision")
    input_revision = snapshot.get("input_revision")
    active = snapshot.get("active")
    exit_code = snapshot.get("exit_code")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Operator Panel status revision must be non-negative")
    if (
        isinstance(input_revision, bool)
        or not isinstance(input_revision, int)
        or input_revision < 0
    ):
        raise ValueError("Operator Panel input revision must be non-negative")
    if not isinstance(active, bool):
        raise ValueError("Operator Panel status active must be boolean")
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
        raise ValueError("Operator Panel status exit_code must be integer or null")
    text_fields = (
        "run_id",
        "state",
        "workflow",
        "name",
        "started_at",
        "finished_at",
        "input_phase",
        "input_detail",
    )
    if any(not isinstance(snapshot.get(field), str) for field in text_fields):
        raise ValueError("Operator Panel status identity fields must be strings")
    state = snapshot["state"]
    if state not in {
        "idle",
        "running",
        "waiting_for_input",
        "stopping",
        "stopped",
        "succeeded",
        "failed",
    }:
        raise ValueError(f"Operator Panel status state is unsupported: {state!r}")
    status_line = snapshot.get("status_line")
    progress = snapshot.get("progress")
    input_actions = snapshot.get("input_actions")
    if not isinstance(status_line, str):
        raise ValueError("Operator Panel status_line must be a string")
    if not isinstance(progress, list) or not all(isinstance(item, dict) for item in progress):
        raise ValueError("Operator Panel progress must be a list of objects")
    progress_ids: list[str] = []
    for item in progress:
        if set(item) != {"id", "label", "current", "total", "phase", "detail"}:
            raise ValueError("Operator Panel progress entry is invalid")
        progress_id = item["id"]
        if (
            not isinstance(progress_id, str)
            or not progress_id
            or any(not isinstance(item[field], str) for field in ("label", "phase", "detail"))
        ):
            raise ValueError("Operator Panel progress identity is invalid")
        current = item["current"]
        total = item["total"]
        if (
            isinstance(current, bool)
            or not isinstance(current, (int, float))
            or not isfinite(current)
            or current < 0
            or total is not None
            and (
                isinstance(total, bool)
                or not isinstance(total, (int, float))
                or not isfinite(total)
                or total <= 0
                or current > total
            )
        ):
            raise ValueError("Operator Panel progress values are invalid")
        progress_ids.append(progress_id)
    if len(set(progress_ids)) != len(progress_ids):
        raise ValueError("Operator Panel progress ids must not contain duplicates")
    if not isinstance(input_actions, list) or not all(
        isinstance(item, dict) for item in input_actions
    ):
        raise ValueError("Operator Panel input_actions must be a list of objects")
    for action in input_actions:
        if set(action) != {"id", "label", "tone"} or not all(
            isinstance(action[key], str) for key in ("id", "label", "tone")
        ):
            raise ValueError("Operator Panel input action is invalid")
        if (
            not action["id"]
            or not action["label"]
            or action["tone"] not in {"default", "primary", "danger", "quiet"}
        ):
            raise ValueError("Operator Panel input action values are invalid")
    action_ids = [action["id"] for action in input_actions]
    if len(set(action_ids)) != len(action_ids):
        raise ValueError("Operator Panel input action ids must not contain duplicates")
    return {
        "schema_version": FOXGLOVE_WORKFLOW_STATUS_SCHEMA_VERSION,
        "source_schema_version": WORKFLOW_STATUS_SCHEMA_VERSION,
        "available": True,
        "revision": revision,
        "input_revision": input_revision,
        "input_phase": snapshot["input_phase"],
        "input_detail": snapshot["input_detail"],
        "run_id": snapshot["run_id"],
        "state": state,
        "active": active,
        "workflow": snapshot["workflow"],
        "name": snapshot["name"],
        "started_at": snapshot["started_at"],
        "finished_at": snapshot["finished_at"],
        "exit_code": exit_code,
        "progress": progress,
        "status_line": status_line,
        "input_actions": input_actions,
    }


def prepare_collection_action(
    snapshot: object,
    *,
    action_id: str,
    expected_phase: str,
) -> CollectionActionRequest:
    """Validate an action against one exact active collection input gate."""

    telemetry = foxglove_workflow_status(snapshot)
    if not telemetry["active"] or telemetry["workflow"] != "collect":
        raise ValueError("no active collection session")
    if telemetry["state"] != "waiting_for_input":
        raise ValueError(f"collection is not accepting input ({telemetry['state']})")
    if telemetry["input_phase"] != expected_phase:
        raise ValueError(
            f"collection phase is {telemetry['input_phase']!r}, expected {expected_phase!r}"
        )
    action_ids = {action["id"] for action in telemetry["input_actions"]}
    if action_id not in action_ids:
        raise ValueError(f"action {action_id!r} is not currently available")
    run_id = telemetry["run_id"]
    input_revision = telemetry["input_revision"]
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("collection run id is unavailable")
    if not isinstance(input_revision, int):
        raise ValueError("collection input revision is unavailable")
    return CollectionActionRequest(
        action_id=action_id,
        run_id=run_id,
        input_revision=input_revision,
    )


def prepare_collection_stop(snapshot: object) -> str:
    """Validate a stop request against the exact active collection run."""

    telemetry = foxglove_workflow_status(snapshot)
    if not telemetry["active"] or telemetry["workflow"] != "collect":
        raise ValueError("no active collection session")
    if telemetry["state"] == "stopping":
        raise ValueError("collection session is already stopping")
    run_id = telemetry["run_id"]
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("collection run id is unavailable")
    return run_id


def select_layout_id(layouts: Any, *, name: str) -> str | None:
    """Select at most one exact-name organization layout."""

    if not isinstance(layouts, list):
        raise ValueError("Foxglove layout list response must be an array")
    matches: list[str] = []
    for index, item in enumerate(layouts):
        if not isinstance(item, dict):
            raise ValueError(f"Foxglove layout list item {index} must be an object")
        if item.get("name") != name:
            continue
        layout_id = item.get("id")
        if not isinstance(layout_id, str) or not layout_id:
            raise ValueError(f"Foxglove layout named {name!r} has no valid id")
        matches.append(layout_id)
    if len(matches) > 1:
        raise ValueError(
            f"Foxglove organization contains {len(matches)} layouts named {name!r}; "
            "refusing an ambiguous update"
        )
    return matches[0] if matches else None


def layout_payload(
    data: Any,
    *,
    name: str,
    folder: str,
    permission: str,
) -> dict[str, Any]:
    """Build one validated organization-layout write payload."""

    if not isinstance(data, dict):
        raise ValueError("committed Foxglove layout must contain one JSON object")
    if permission != "ORG_WRITE":
        raise ValueError("API-key-managed Foxglove layouts must use ORG_WRITE")
    if not isinstance(name, str) or not name:
        raise ValueError("Foxglove layout name must be a non-empty string")
    if not isinstance(folder, str) or not folder or "/" in folder:
        raise ValueError("Foxglove layout folder must be non-empty without a slash")
    return {
        "name": name,
        "folderName": folder,
        "permission": permission,
        "data": data,
    }


class FoxgloveLayoutsClient:
    """Minimal fail-closed client for exact-name organization layout upserts."""

    def __init__(self, *, api_key: str) -> None:
        if not api_key:
            raise ValueError("FOXGLOVE_API_KEY is required")
        self._api_key = api_key

    def request(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "embodied-ops-foxglove-layout-publisher/1",
        }
        if payload is not None:
            body = json.dumps(
                payload,
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            error_body = exc.read(64 * 1024).decode(errors="replace")
            error_body = error_body.replace(self._api_key, "[REDACTED]")
            raise RuntimeError(
                f"Foxglove API {method} failed with HTTP {exc.code}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Foxglove API {method} request failed: {exc}") from exc
        if len(response_body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Foxglove API response exceeded 8 MiB")
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Foxglove API returned invalid JSON") from exc

    def upsert(
        self,
        data: Any,
        *,
        name: str,
        folder: str,
        permission: str,
    ) -> PublishedLayout:
        layouts = self.request("GET", f"{FOXGLOVE_LAYOUTS_API}?includeData=false")
        existing_id = select_layout_id(layouts, name=name)
        payload = layout_payload(
            data,
            name=name,
            folder=folder,
            permission=permission,
        )
        if existing_id is None:
            result = self.request("POST", FOXGLOVE_LAYOUTS_API, payload=payload)
            action = "created"
        else:
            encoded_id = urllib.parse.quote(existing_id, safe="")
            result = self.request(
                "PATCH",
                f"{FOXGLOVE_LAYOUTS_API}/{encoded_id}",
                payload=payload,
            )
            action = "updated"
        if not isinstance(result, dict):
            raise RuntimeError("Foxglove layout write response must be an object")
        result_id = result.get("id")
        result_name = result.get("name")
        if not isinstance(result_id, str) or result_name != name:
            raise RuntimeError("Foxglove layout write response identity mismatch")
        return PublishedLayout(id=result_id, name=result_name, action=action)


def parse_args() -> Namespace:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--folder", required=True)
    parser.add_argument(
        "--permission",
        choices=("ORG_WRITE",),
        default="ORG_WRITE",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.layout.open(encoding="utf-8") as stream:
        data = json.load(stream)
    client = FoxgloveLayoutsClient(api_key=os.environ.get("FOXGLOVE_API_KEY", ""))
    result = client.upsert(
        data,
        name=args.name,
        folder=args.folder,
        permission=args.permission,
    )
    success(f"Foxglove layout {result.action}: {result.name} ({result.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
