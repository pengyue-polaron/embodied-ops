from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from embodied_ops.operator_panel import (
    DocumentKind,
    InputAction,
    InvalidEvent,
    OperatorPanelApplication,
    PANEL_CATALOG_SCHEMA_VERSION,
    PanelCapabilities,
    RepositoryDocumentStore,
    WorkflowLaunch,
    select_field,
    text_field,
    normalize_camera_health,
    unavailable_camera_health,
    parse_event,
    strip_protocol_events,
    validate_panel_catalog,
)
from embodied_ops.operator_panel.process import WorkflowProcess


def test_workflow_process_accepts_one_announced_input(tmp_path: Path) -> None:
    process = WorkflowProcess(tmp_path)
    launch = WorkflowLaunch(
        workflow="test",
        name="test",
        command=(
            sys.executable,
            "-u",
            "-c",
            'print(\'@@OPERATOR_PANEL {"input":["enter"]}\'); '
            "input(); print('workflow complete')",
        ),
        input_actions=(InputAction("enter", "Next", "\n", "primary"),),
    )

    process.start(launch)
    with pytest.raises(RuntimeError, match="already active"):
        process.start(launch)
    status = _wait_for(process, lambda value: bool(value["input_actions"]))
    assert status["input_actions"] == [{"id": "enter", "label": "Next", "tone": "primary"}]
    process.send("enter")
    with pytest.raises(RuntimeError, match="not waiting"):
        process.send("enter")

    status = _wait_for(
        process,
        lambda value: not value["active"] and "workflow complete" in value["logs"],
    )
    assert status["exit_code"] == 0


def test_workflow_process_separates_progress_and_live_status_from_logs(
    tmp_path: Path,
) -> None:
    process = WorkflowProcess(tmp_path)
    launch = WorkflowLaunch(
        workflow="test",
        name="progress test",
        command=(
            sys.executable,
            "-u",
            "-c",
            "import os, time; "
            "assert os.environ['OPERATOR_PANEL_PROTOCOL'] == '1'; "
            'print(\'@@OPERATOR_PANEL {"progress":{"id":"inference",\''
            '\'"label":"Inference","current":2,"total":4,\''
            '\'"phase":"EXECUTE","detail":"action 8/16"}}\'); '
            "print('[RUN] call 1'); print('[RUN] call 2'); time.sleep(0.5)",
        ),
    )

    process.start(launch)
    status = _wait_for(
        process,
        lambda value: bool(value["progress"]) and value["status_line"] != "",
    )

    assert status["progress"] == [
        {
            "id": "inference",
            "label": "Inference",
            "current": 2,
            "total": 4,
            "phase": "EXECUTE",
            "detail": "action 8/16",
        }
    ]
    assert status["status_line"] == "[RUN] call 2"
    assert all(not line.startswith("@@OPERATOR_PANEL") for line in status["logs"])
    assert all(not line.startswith("[RUN]") for line in status["logs"])

    status = _wait_for(process, lambda value: not value["active"])
    assert status["exit_code"] == 0
    assert status["status_line"] == ""


def test_protocol_rejects_invalid_progress() -> None:
    event = parse_event(
        '@@OPERATOR_PANEL {"progress":{"id":"inference","label":"Inference",'
        '"current":5,"total":4,"phase":"EXECUTE","detail":""}}'
    )

    assert isinstance(event, InvalidEvent)
    assert event.reason == "progress total must be positive and at least current"


def test_protocol_events_can_be_removed_without_exposing_the_wire_prefix() -> None:
    value = 'started\n@@OPERATOR_PANEL {"progress":{"id":"inference"}}\nfinished\n'

    assert strip_protocol_events(value) == "started\nfinished\n"


def test_repository_document_store_uses_the_declared_format(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "configs/demo"
    directory.mkdir(parents=True)
    template = directory / "base.yaml"
    template.write_text("value: 1\n")

    def validate(path: Path) -> None:
        key, separator, value = path.read_text().strip().partition(":")
        if key != "value" or separator != ":" or not value.strip().isdigit():
            raise ValueError("demo config requires one integer value")

    store = RepositoryDocumentStore(
        tmp_path,
        (
            DocumentKind(
                kind_id="demo",
                label="Demo",
                directory=Path("configs/demo"),
                suffix=".yaml",
                language="YAML",
                validate=validate,
            ),
        ),
    )
    assert store.catalog() == [
        {
            "id": "demo",
            "label": "Demo",
            "extension": ".yaml",
            "language": "YAML",
            "templates": [{"value": "configs/demo/base.yaml", "label": "base"}],
        }
    ]
    assert store.template("demo", "configs/demo/base.yaml")["content"] == "value: 1\n"
    assert store.validate("demo", "second", "value: 2")["valid"] is True
    assert store.create("demo", "second", "value: 2") == {"created": "configs/demo/second.yaml"}
    assert (directory / "second.yaml").read_text() == "value: 2\n"
    with pytest.raises(FileExistsError, match="already exists"):
        store.create("demo", "second", "value: 3")


def test_repository_document_store_rejects_an_invalid_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="suffix"):
        RepositoryDocumentStore(
            tmp_path,
            (
                DocumentKind(
                    kind_id="demo",
                    label="Demo",
                    directory=Path("configs/demo"),
                    suffix="yaml",
                    language="YAML",
                    validate=lambda _path: None,
                ),
            ),
        )


def test_minimal_adapter_does_not_implement_optional_capabilities(tmp_path: Path) -> None:
    class MinimalAdapter:
        repo_root = tmp_path
        capabilities = PanelCapabilities()

        def catalog(self):
            return _minimal_catalog()

        def build_launch(self, workflow, values):
            raise AssertionError((workflow, values))

    app = OperatorPanelApplication(MinimalAdapter())

    with pytest.raises(LookupError, match="camera"):
        app.camera_health()
    with pytest.raises(LookupError, match="configuration"):
        app.config_template({})
    with pytest.raises(LookupError, match="registration"):
        app.register({})


def test_panel_catalog_schema_standardizes_product_workflows_and_fields() -> None:
    catalog = _minimal_catalog()
    catalog["workflows"] = [
        {
            "id": "collect",
            "label": "Collect",
            "eyebrow": "DATA COLLECTION",
            "title": "Collect episodes",
            "submit_label": "Start collection",
            "fields": [
                select_field(
                    "robot",
                    "Robot",
                    [{"value": "demo", "label": "Demo robot"}],
                ),
                text_field("task", "Task", placeholder="pick the object"),
            ],
        }
    ]

    assert validate_panel_catalog(catalog) is catalog
    catalog["workflows"][0]["fields"][0]["unknown"] = True
    with pytest.raises(ValueError, match="invalid keys"):
        validate_panel_catalog(catalog)


def test_camera_health_contract_is_normalized() -> None:
    assert normalize_camera_health(
        {
            "ok": True,
            "streams": {
                "wrist": {
                    "ready": True,
                    "fresh": True,
                    "preview_fps": 9,
                    "age_s": 0.03,
                    "error": None,
                }
            },
        }
    ) == {
        "available": True,
        "ok": True,
        "streams": {
            "wrist": {
                "ready": True,
                "fresh": True,
                "preview_fps": 9.0,
                "age_s": 0.03,
                "error": None,
            }
        },
    }
    assert unavailable_camera_health("not running") == {
        "available": False,
        "ok": False,
        "streams": {},
        "reason": "not running",
    }
    with pytest.raises(ValueError, match="finite and non-negative"):
        normalize_camera_health(
            {
                "ok": False,
                "streams": {
                    "wrist": {
                        "ready": True,
                        "fresh": False,
                        "preview_fps": float("nan"),
                        "age_s": None,
                        "error": None,
                    }
                },
            }
        )


def _wait_for(process: WorkflowProcess, predicate) -> dict:
    deadline = time.monotonic() + 3.0
    status = process.snapshot()
    while not predicate(status) and time.monotonic() < deadline:
        time.sleep(0.01)
        status = process.snapshot()
    return status


def _minimal_catalog() -> dict:
    return {
        "schema_version": PANEL_CATALOG_SCHEMA_VERSION,
        "product": {"brand": "DEMO", "title": "Control"},
        "cameras": [],
        "camera_controls": [],
        "workflows": [],
        "registrations": [],
        "configuration_types": [],
        "configuration_groups": [],
    }
