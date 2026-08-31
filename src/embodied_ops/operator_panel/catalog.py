"""Versioned catalog schema and form builders for the standard Operator Panel."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


PANEL_CATALOG_SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]*")
_TOP_LEVEL_KEYS = {
    "schema_version",
    "product",
    "cameras",
    "camera_controls",
    "workflows",
    "registrations",
    "configuration_types",
    "configuration_groups",
}

_CORE_WORKFLOW_ORDER = (
    "hardware",
    "collect",
    "reset",
    "dataset-doctor",
    "export-v21",
)
_CORE_WORKFLOW_COPY = {
    "hardware": {
        "label": "Hardware",
        "eyebrow": "READINESS",
        "title": "Check hardware",
        "description": "Check configured robot and camera readiness without moving the robot.",
        "submit_label": "Run hardware check",
    },
    "collect": {
        "label": "Collect",
        "eyebrow": "DATA COLLECTION",
        "title": "Collect episodes",
        "description": (
            "Reset before capture, record into the canonical LeRobot dataset, trim "
            "leading stillness, and reset after each episode."
        ),
        "submit_label": "Start collection",
    },
    "reset": {
        "label": "Reset",
        "eyebrow": "RESET",
        "title": "Reset robot",
        "description": "Move the robot to its tracked collection start state.",
        "submit_label": "Run reset",
        "tone": "danger",
    },
    "dataset-doctor": {
        "label": "Dataset doctor",
        "eyebrow": "DATASET",
        "title": "Inspect canonical data",
        "description": "Validate episodes, frames, tasks, metadata, and referenced media.",
        "submit_label": "Run doctor",
    },
    "export-v21": {
        "label": "Export v2.1",
        "eyebrow": "DATASET",
        "title": "Export LeRobot v2.1",
        "description": "Build a tracked LeRobot v2.1 derivative from canonical data.",
        "submit_label": "Export dataset",
    },
}


def standard_panel_product(brand: str) -> dict[str, str]:
    """Return the shared product identity used by every robot adapter."""

    return {"brand": _text(brand, "product brand"), "title": "Operator Panel"}


def standard_camera_controls(*, stop_confirm: str) -> list[dict[str, Any]]:
    """Return the common lifecycle controls for persistent camera previews."""

    return [
        {
            "label": "Start cameras",
            "workflow": "camera",
            "values": {"action": "start"},
        },
        {
            "label": "Stop cameras",
            "workflow": "camera",
            "values": {"action": "stop"},
            "tone": "danger",
            "confirm": _text(stop_confirm, "camera stop confirmation"),
        },
    ]


def standard_core_workflows(
    *,
    hardware_fields: list[dict[str, Any]],
    collect_fields: list[dict[str, Any]],
    reset_fields: list[dict[str, Any]],
    dataset_fields: list[dict[str, Any]],
    reset_confirm: str,
) -> list[dict[str, Any]]:
    """Build the ordered workflow surface shared by all collection robots."""

    fields = {
        "hardware": hardware_fields,
        "collect": collect_fields,
        "reset": reset_fields,
        "dataset-doctor": dataset_fields,
        "export-v21": dataset_fields,
    }
    workflows = []
    for workflow_id in _CORE_WORKFLOW_ORDER:
        workflow = {
            "id": workflow_id,
            **_CORE_WORKFLOW_COPY[workflow_id],
            "fields": deepcopy(fields[workflow_id]),
        }
        if workflow_id == "reset":
            workflow["confirm"] = _text(reset_confirm, "reset confirmation")
        workflows.append(workflow)
    return workflows


def order_workflow_forms(workflows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the shared collection journey first and preserve extension order."""

    ranks = {workflow_id: index for index, workflow_id in enumerate(_CORE_WORKFLOW_ORDER)}
    return [
        item
        for _, item in sorted(
            enumerate(workflows),
            key=lambda pair: (ranks.get(pair[1].get("id"), len(ranks)), pair[0]),
        )
    ]


def option(value: str, label: str, *, depends_value: str | None = None) -> dict[str, str]:
    result = {"value": _text(value, "option value"), "label": _text(label, "option label")}
    if depends_value is not None:
        result["depends_value"] = _text(depends_value, "option dependency")
    return result


def select_field(
    name: str,
    label: str,
    options: list[dict[str, str]],
    *,
    default: str | None = None,
    required: bool = True,
    depends_on: str | None = None,
) -> dict[str, Any]:
    field: dict[str, Any] = {
        "name": _identifier(name, "field name"),
        "label": _text(label, "field label"),
        "type": "select",
        "required": _boolean(required, "field required"),
        "options": [dict(item) for item in options],
    }
    if default is not None:
        field["default"] = _text(default, "field default")
    if depends_on is not None:
        field["depends_on"] = _identifier(depends_on, "field dependency")
    return field


def text_field(
    name: str,
    label: str,
    *,
    placeholder: str,
    required: bool = True,
    help_text: str | None = None,
) -> dict[str, Any]:
    field: dict[str, Any] = {
        "name": _identifier(name, "field name"),
        "label": _text(label, "field label"),
        "type": "text",
        "required": _boolean(required, "field required"),
        "placeholder": _text(placeholder, "field placeholder"),
    }
    if help_text is not None:
        field["help_text"] = _text(help_text, "field help text")
    return field


def combobox_field(
    name: str,
    label: str,
    options: list[dict[str, str]],
    *,
    placeholder: str,
    help_text: str,
    depends_on: str | None = None,
) -> dict[str, Any]:
    field = text_field(name, label, placeholder=placeholder, help_text=help_text)
    field["type"] = "combobox"
    field["options"] = [dict(item) for item in options]
    if depends_on is not None:
        field["depends_on"] = _identifier(depends_on, "field dependency")
    return field


def checkbox_field(name: str, label: str, *, default: bool = False) -> dict[str, Any]:
    return {
        "name": _identifier(name, "field name"),
        "label": _text(label, "field label"),
        "type": "checkbox",
        "default": _boolean(default, "field default"),
    }


def validate_panel_catalog(value: object) -> dict[str, Any]:
    """Return a valid standard catalog or reject schema drift before serving."""

    catalog = _object(value, "Operator Panel catalog")
    _exact_keys(catalog, _TOP_LEVEL_KEYS, "Operator Panel catalog")
    if catalog.get("schema_version") != PANEL_CATALOG_SCHEMA_VERSION:
        raise ValueError(
            f"Operator Panel catalog schema_version must be {PANEL_CATALOG_SCHEMA_VERSION}"
        )

    product = _object(catalog["product"], "Operator Panel product")
    _exact_keys(product, {"brand", "title"}, "Operator Panel product")
    _text(product["brand"], "product brand")
    _text(product["title"], "product title")

    cameras = _list(catalog["cameras"], "Operator Panel cameras")
    _unique_ids(cameras, "camera", _validate_camera)
    controls = _list(catalog["camera_controls"], "Operator Panel camera controls")
    for index, control in enumerate(controls):
        _validate_camera_control(control, f"camera control {index}")

    workflows = _list(catalog["workflows"], "Operator Panel workflows")
    registrations = _list(catalog["registrations"], "Operator Panel registrations")
    workflow_ids = _unique_ids(workflows, "workflow", _validate_form)
    registration_ids = _unique_ids(registrations, "registration", _validate_form)
    overlap = sorted(workflow_ids & registration_ids)
    if overlap:
        raise ValueError(f"workflow and registration ids must be unique: {overlap}")

    configuration_types = _list(
        catalog["configuration_types"], "Operator Panel configuration types"
    )
    _unique_ids(configuration_types, "configuration type", _validate_configuration_type)
    groups = _list(catalog["configuration_groups"], "Operator Panel configuration groups")
    for index, group in enumerate(groups):
        _validate_configuration_group(group, f"configuration group {index}")
    return catalog


def validate_workflow_submission(
    catalog: object,
    workflow_id: object,
    values: object,
) -> dict[str, Any]:
    """Validate one workflow or declared camera-control submission."""

    validated = validate_panel_catalog(catalog)
    identity = _identifier(workflow_id, "workflow id")
    submitted = _object(values, f"workflow {identity!r} values")
    for raw_form in validated["workflows"]:
        form = _object(raw_form, "workflow form")
        if form["id"] == identity:
            return _validate_submission_values(form, submitted, f"workflow {identity!r}")
    matching_controls = [
        _object(item, "camera control")
        for item in validated["camera_controls"]
        if _object(item, "camera control")["workflow"] == identity
    ]
    if any(control["values"] == submitted for control in matching_controls):
        return dict(submitted)
    if matching_controls:
        raise ValueError(f"workflow {identity!r} values do not match a declared camera control")
    raise ValueError(f"unknown workflow: {identity!r}")


def validate_registration_submission(
    catalog: object,
    registration_id: object,
    values: object,
) -> dict[str, Any]:
    """Validate one registration submission against its declared form."""

    validated = validate_panel_catalog(catalog)
    identity = _identifier(registration_id, "registration id")
    submitted = _object(values, f"registration {identity!r} values")
    for raw_form in validated["registrations"]:
        form = _object(raw_form, "registration form")
        if form["id"] == identity:
            return _validate_submission_values(
                form,
                submitted,
                f"registration {identity!r}",
            )
    raise ValueError(f"unknown registration: {identity!r}")


def _validate_submission_values(
    form: dict[str, Any],
    values: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    fields = {field["name"]: _object(field, f"{label} field") for field in form["fields"]}
    unknown = sorted(set(values) - set(fields))
    if unknown:
        raise ValueError(f"{label} has unknown values: {unknown}")

    normalized: dict[str, Any] = {}
    for name, field in fields.items():
        if name in values:
            value = values[name]
        elif "default" in field:
            value = field["default"]
        elif field.get("required", field["type"] != "checkbox"):
            raise ValueError(f"{label} is missing required value: {name!r}")
        else:
            continue

        field_type = field["type"]
        if field_type == "checkbox":
            _boolean(value, f"{label} value {name!r}")
        else:
            if not isinstance(value, str) or value != value.strip():
                raise ValueError(f"{label} value {name!r} must be text without surrounding space")
            if field.get("required", True) and not value:
                raise ValueError(f"{label} value {name!r} must not be empty")
            if field_type == "select":
                available = [
                    option["value"]
                    for option in field["options"]
                    if "depends_on" not in field
                    or option.get("depends_value")
                    == normalized.get(
                        field["depends_on"],
                        values.get(field["depends_on"]),
                    )
                ]
                if value not in available:
                    raise ValueError(f"{label} value {name!r} is not an available select option")
        normalized[name] = value
    return normalized


def _validate_camera(value: object, label: str) -> None:
    camera = _object(value, label)
    allowed = {"id", "label", "url", "port", "path"}
    if not set(camera).issubset(allowed) or not {"id", "label"} <= set(camera):
        raise ValueError(f"{label} has invalid keys: {sorted(camera)}")
    _identifier(camera["id"], f"{label} id")
    _text(camera["label"], f"{label} label")
    has_url = "url" in camera
    has_local_endpoint = "port" in camera or "path" in camera
    if has_url == has_local_endpoint:
        raise ValueError(f"{label} requires exactly one URL or port/path endpoint")
    if has_url:
        _text(camera["url"], f"{label} URL")
        return
    port = camera.get("port")
    path = camera.get("path")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"{label} port must be an integer in 1..65535")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"{label} path must start with '/'")


def _validate_camera_control(value: object, label: str) -> None:
    control = _object(value, label)
    required = {"label", "workflow", "values"}
    allowed = required | {"tone", "confirm"}
    _required_allowed_keys(control, required, allowed, label)
    _text(control["label"], f"{label} label")
    _identifier(control["workflow"], f"{label} workflow")
    _object(control["values"], f"{label} values")
    _optional_tone_and_confirm(control, label)


def _validate_form(value: object, label: str) -> None:
    form = _object(value, label)
    required = {"id", "label", "eyebrow", "title", "submit_label", "fields"}
    allowed = required | {"description", "tone", "confirm"}
    _required_allowed_keys(form, required, allowed, label)
    _identifier(form["id"], f"{label} id")
    for key in ("label", "eyebrow", "title", "submit_label"):
        _text(form[key], f"{label} {key}")
    if "description" in form:
        _text(form["description"], f"{label} description")
    _optional_tone_and_confirm(form, label)
    fields = _list(form["fields"], f"{label} fields")
    if not fields:
        raise ValueError(f"{label} fields must not be empty")
    names = _unique_ids(fields, f"{label} field", _validate_field, id_key="name")
    for raw_field in fields:
        field = _object(raw_field, f"{label} field")
        for key in ("depends_on", "derive_from"):
            if key in field and field[key] not in names:
                raise ValueError(f"{label} field {field['name']!r} references unknown {key}")


def _validate_field(value: object, label: str) -> None:
    field = _object(value, label)
    field_type = field.get("type")
    common = {"name", "label", "type"}
    optional = {
        "required",
        "default",
        "placeholder",
        "help_text",
        "options",
        "depends_on",
        "derive_from",
        "transform",
    }
    _required_allowed_keys(field, common, common | optional, label)
    _identifier(field["name"], f"{label} name")
    _text(field["label"], f"{label} label")
    if field_type not in {"text", "select", "combobox", "checkbox"}:
        raise ValueError(f"{label} has unsupported type: {field_type!r}")
    if "required" in field:
        _boolean(field["required"], f"{label} required")
    if field_type == "checkbox":
        if set(field) - (common | {"default"}):
            raise ValueError(f"{label} checkbox has unsupported keys")
        _boolean(field.get("default", False), f"{label} default")
        return
    for key in ("default", "placeholder", "help_text", "depends_on", "derive_from"):
        if key in field:
            _text(field[key], f"{label} {key}")
    if field_type in {"select", "combobox"}:
        options = _list(field.get("options"), f"{label} options")
        for index, item in enumerate(options):
            _validate_option(item, f"{label} option {index}")
    elif "options" in field:
        raise ValueError(f"{label} text field must not define options")
    if "transform" in field and field["transform"] != "snake_case":
        raise ValueError(f"{label} has unsupported transform")


def _validate_option(value: object, label: str) -> None:
    item = _object(value, label)
    _required_allowed_keys(item, {"value", "label"}, {"value", "label", "depends_value"}, label)
    _text(item["value"], f"{label} value", allow_empty=True)
    _text(item["label"], f"{label} label")
    if "depends_value" in item:
        _text(item["depends_value"], f"{label} dependency")


def _validate_configuration_type(value: object, label: str) -> None:
    item = _object(value, label)
    _exact_keys(item, {"id", "label", "extension", "language", "templates"}, label)
    _identifier(item["id"], f"{label} id")
    for key in ("label", "extension", "language"):
        _text(item[key], f"{label} {key}")
    templates = _list(item["templates"], f"{label} templates")
    for index, template in enumerate(templates):
        _validate_option(template, f"{label} template {index}")


def _validate_configuration_group(value: object, label: str) -> None:
    group = _object(value, label)
    _exact_keys(group, {"label", "items"}, label)
    _text(group["label"], f"{label} label")
    for index, item in enumerate(_list(group["items"], f"{label} items")):
        _validate_option(item, f"{label} item {index}")


def _optional_tone_and_confirm(value: dict[str, Any], label: str) -> None:
    if "tone" in value and value["tone"] not in {"default", "danger"}:
        raise ValueError(f"{label} has unsupported tone")
    if "confirm" in value:
        _text(value["confirm"], f"{label} confirmation")


def _unique_ids(values, label, validate, *, id_key: str = "id") -> set[str]:
    result: set[str] = set()
    for index, value in enumerate(values):
        item_label = f"{label} {index}"
        validate(value, item_label)
        identity = _object(value, item_label)[id_key]
        if identity in result:
            raise ValueError(f"duplicate {label} id: {identity!r}")
        result.add(identity)
    return result


def _required_allowed_keys(value, required, allowed, label) -> None:
    keys = set(value)
    if not required <= keys or not keys <= allowed:
        raise ValueError(f"{label} has invalid keys: {sorted(keys)}")


def _exact_keys(value, expected, label) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} has invalid keys: {sorted(value)}")


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase identifier")
    return value


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or value != value.strip() or (not allow_empty and not value):
        raise ValueError(f"{label} must be text without surrounding space")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value
