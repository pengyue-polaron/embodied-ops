import pytest

from embodied_ops.foxglove import (
    collection_console_panel_config,
    foxglove_workflow_status,
    layout_payload,
    prepare_collection_action,
    prepare_collection_stop,
    select_layout_id,
)
from embodied_ops.operator_panel import WORKFLOW_STATUS_SCHEMA_VERSION


SERVICES = {
    "start": "/robot/ops/collection/start",
    "save": "/robot/ops/collection/save",
    "discard": "/robot/ops/collection/discard",
    "reset": "/robot/ops/collection/reset",
    "stop": "/robot/ops/collection/stop",
}

WORKFLOW_SNAPSHOT = {
    "schema_version": WORKFLOW_STATUS_SCHEMA_VERSION,
    "revision": 7,
    "input_revision": 3,
    "run_id": "run-1",
    "state": "waiting_for_input",
    "active": True,
    "workflow": "collect",
    "name": "Collect",
    "command": ["private-command"],
    "started_at": "2026-09-01T00:00:00+00:00",
    "finished_at": "",
    "exit_code": None,
    "progress": [
        {
            "id": "episode",
            "label": "Episode",
            "current": 1,
            "total": 3,
            "phase": "ready",
            "detail": "Episode 1",
        }
    ],
    "status_line": "waiting",
    "input_actions": [{"id": "start", "label": "Start recording", "tone": "primary"}],
    "input_phase": "ready",
    "input_detail": "Episode 1",
    "logs": ["private child log"],
}


def test_collection_console_config_is_runtime_supplied_and_exact() -> None:
    assert collection_console_panel_config(
        status_topic="/robot/ops/workflow_status",
        services=SERVICES,
    ) == {
        "schemaVersion": 1,
        "statusTopic": "/robot/ops/workflow_status",
        "services": SERVICES,
        "staleAfterMs": 3000,
    }

    with pytest.raises(ValueError, match="exactly"):
        collection_console_panel_config(
            status_topic="/robot/ops/workflow_status",
            services={"start": SERVICES["start"]},
        )
    with pytest.raises(ValueError, match="unique"):
        collection_console_panel_config(
            status_topic="/robot/ops/workflow_status",
            services={name: "/same" for name in SERVICES},
        )


def test_workflow_status_is_validated_and_sanitized_for_foxglove() -> None:
    telemetry = foxglove_workflow_status(WORKFLOW_SNAPSHOT)

    assert telemetry["schema_version"] == 2
    assert telemetry["source_schema_version"] == WORKFLOW_STATUS_SCHEMA_VERSION
    assert telemetry["state"] == "waiting_for_input"
    assert "command" not in telemetry
    assert "logs" not in telemetry
    assert foxglove_workflow_status(None, error="panel not running") == {
        "schema_version": 2,
        "available": False,
        "error": "panel not running",
    }


def test_collection_control_requires_the_exact_active_input_gate() -> None:
    action = prepare_collection_action(
        WORKFLOW_SNAPSHOT,
        action_id="start",
        expected_phase="ready",
    )

    assert action.run_id == "run-1"
    assert action.input_revision == 3
    assert prepare_collection_stop(WORKFLOW_SNAPSHOT) == "run-1"
    with pytest.raises(ValueError, match="expected 'recording'"):
        prepare_collection_action(
            WORKFLOW_SNAPSHOT,
            action_id="start",
            expected_phase="recording",
        )
    with pytest.raises(ValueError, match="not currently available"):
        prepare_collection_action(
            WORKFLOW_SNAPSHOT,
            action_id="discard",
            expected_phase="ready",
        )
    with pytest.raises(ValueError, match="already stopping"):
        prepare_collection_stop({**WORKFLOW_SNAPSHOT, "state": "stopping"})


def test_layout_publish_selects_one_exact_organization_layout() -> None:
    layouts = [
        {"id": "other", "name": "Other Layout"},
        {"id": "robot-layout", "name": "Robot Operations"},
    ]

    assert select_layout_id(layouts, name="Robot Operations") == "robot-layout"
    assert layout_payload(
        {"layout": "Tabs!"},
        name="Robot Operations",
        folder="Robots",
        permission="ORG_WRITE",
    ) == {
        "name": "Robot Operations",
        "folderName": "Robots",
        "permission": "ORG_WRITE",
        "data": {"layout": "Tabs!"},
    }


def test_layout_publish_rejects_ambiguous_or_unwritable_layouts() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        select_layout_id(
            [
                {"id": "first", "name": "Robot Operations"},
                {"id": "second", "name": "Robot Operations"},
            ],
            name="Robot Operations",
        )

    with pytest.raises(ValueError, match="ORG_WRITE"):
        layout_payload(
            {},
            name="Robot Operations",
            folder="Robots",
            permission="ORG_READ",
        )
