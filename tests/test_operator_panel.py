from __future__ import annotations

import sys
import time
import subprocess
from pathlib import Path

import pytest

from embodied_ops.operator_panel import (
    DocumentKind,
    InputAction,
    InvalidEvent,
    OperatorPanelApplication,
    PANEL_CATALOG_SCHEMA_VERSION,
    PANEL_EVENT_SCHEMA_VERSION,
    PanelCapabilities,
    RepositoryDocumentStore,
    WorkflowLaunch,
    WORKFLOW_STATUS_SCHEMA_VERSION,
    announce_input,
    option,
    select_field,
    standard_camera_controls,
    standard_core_workflows,
    standard_panel_product,
    text_field,
    normalize_camera_health,
    unavailable_camera_health,
    parse_event,
    strip_protocol_events,
    validate_panel_catalog,
    validate_workflow_submission,
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
            'print(\'@@OPERATOR_PANEL {"input":["unknown","enter"]}\'); '
            "input(); print('workflow complete')",
        ),
        input_actions=(InputAction("enter", "Next", "\n", "primary"),),
    )

    process.start(launch)
    with pytest.raises(RuntimeError, match="already active"):
        process.start(launch)
    status = _wait_for(process, lambda value: bool(value["input_actions"]))
    revision = status["revision"]
    assert status["schema_version"] == WORKFLOW_STATUS_SCHEMA_VERSION
    assert status["run_id"]
    assert status["state"] == "waiting_for_input"
    assert status["input_actions"] == [{"id": "enter", "label": "Next", "tone": "primary"}]
    assert any(
        "undeclared operator-panel input actions: unknown" in line for line in status["logs"]
    )
    process.send("enter")
    with pytest.raises(RuntimeError, match="not waiting"):
        process.send("enter")

    status = _wait_for(
        process,
        lambda value: not value["active"] and "workflow complete" in value["logs"],
    )
    assert status["exit_code"] == 0
    assert status["state"] == "succeeded"
    assert status["finished_at"]
    assert status["revision"] > revision


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
            "assert os.environ['OPERATOR_PANEL_PROTOCOL_VERSION'] == '1'; "
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


def test_workflow_process_stops_child_when_panel_owner_disappears(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    stopped = tmp_path / "stopped"
    child_code = (
        "import signal, sys, time; from pathlib import Path; "
        f"ready=Path({str(ready)!r}); stopped=Path({str(stopped)!r}); "
        "stop=lambda *_: (stopped.write_text('stopped'), sys.exit(0)); "
        "signal.signal(signal.SIGINT, stop); ready.write_text('ready'); "
        "deadline=time.monotonic()+5; "
        'exec("while time.monotonic() < deadline:\\n time.sleep(0.05)")'
    )
    owner_code = (
        "import os, sys, time; from pathlib import Path; "
        "from embodied_ops.operator_panel import WorkflowLaunch; "
        "from embodied_ops.operator_panel.process import WorkflowProcess; "
        f"ready=Path({str(ready)!r}); "
        f"process=WorkflowProcess(Path({str(tmp_path)!r})); "
        "process.start(WorkflowLaunch(workflow='test', name='test', "
        f"command=(sys.executable, '-u', '-c', {child_code!r}))); "
        "deadline=time.monotonic()+3; "
        'exec("while not ready.exists() and time.monotonic() < deadline:\\n time.sleep(0.01)"); '
        "assert ready.exists(); os._exit(0)"
    )

    result = subprocess.run([sys.executable, "-c", owner_code], check=False)

    assert result.returncode == 0
    deadline = time.monotonic() + 3.0
    while not stopped.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert stopped.read_text() == "stopped"


def test_protocol_rejects_invalid_progress() -> None:
    event = parse_event(
        '@@OPERATOR_PANEL {"progress":{"id":"inference","label":"Inference",'
        '"current":5,"total":4,"phase":"EXECUTE","detail":""}}'
    )

    assert isinstance(event, InvalidEvent)
    assert event.reason == "progress total must be positive and at least current"


def test_protocol_emits_a_versioned_envelope_and_rejects_invalid_input(capsys, monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_PANEL_PROTOCOL", "1")

    announce_input(("enter",))
    line = capsys.readouterr().out.strip()

    assert line.startswith("@@OPERATOR_PANEL ")
    assert f'"schema_version":{PANEL_EVENT_SCHEMA_VERSION}' in line
    assert parse_event(line).actions == ("enter",)
    invalid = parse_event('@@OPERATOR_PANEL {"input":"enter"}')
    assert isinstance(invalid, InvalidEvent)
    assert invalid.reason == "input actions must be a list"


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


def test_workflow_submission_is_validated_against_the_declared_form() -> None:
    catalog = _minimal_catalog()
    catalog["workflows"] = [
        {
            "id": "collect",
            "label": "Collect",
            "eyebrow": "DATA",
            "title": "Collect",
            "submit_label": "Start",
            "fields": [
                select_field(
                    "config",
                    "Config",
                    [{"value": "demo", "label": "Demo"}],
                    default="demo",
                ),
                text_field("task", "Task", placeholder="pick"),
            ],
        }
    ]

    assert validate_workflow_submission(catalog, "collect", {"task": "pick"}) == {
        "config": "demo",
        "task": "pick",
    }
    with pytest.raises(ValueError, match="unknown values"):
        validate_workflow_submission(
            catalog,
            "collect",
            {"task": "pick", "unexpected": True},
        )
    with pytest.raises(ValueError, match="available select option"):
        validate_workflow_submission(
            catalog,
            "collect",
            {"config": "other", "task": "pick"},
        )
    with pytest.raises(ValueError, match="missing required"):
        validate_workflow_submission(catalog, "collect", {})


def test_standard_panel_catalog_builders_define_one_core_operator_journey() -> None:
    config = select_field(
        "config",
        "Collection config",
        [option("configs/collection/default.toml", "default")],
    )
    workflows = standard_core_workflows(
        hardware_fields=[config],
        collect_fields=[config, text_field("task", "Task prompt", placeholder="pick")],
        reset_fields=[config],
        dataset_fields=[config, text_field("experiment", "Experiment", placeholder="run_v1")],
        reset_confirm="Confirm the workspace is clear before moving the robot?",
    )

    assert standard_panel_product("Demo Robot") == {
        "brand": "Demo Robot",
        "title": "Operator Panel",
    }
    assert [workflow["id"] for workflow in workflows] == [
        "hardware",
        "collect",
        "reset",
        "dataset-doctor",
        "export-v21",
    ]
    assert [workflow["label"] for workflow in workflows] == [
        "Hardware",
        "Collect",
        "Reset",
        "Dataset doctor",
        "Export v2.1",
    ]
    assert workflows[2]["tone"] == "danger"
    assert workflows[3]["fields"] is not workflows[4]["fields"]
    assert standard_camera_controls(stop_confirm="Stop previews?")[1] == {
        "label": "Stop cameras",
        "workflow": "camera",
        "values": {"action": "stop"},
        "tone": "danger",
        "confirm": "Stop previews?",
    }


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
