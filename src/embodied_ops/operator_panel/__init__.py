"""Adapter-driven Web operations for embodied-AI repositories."""

from .contracts import (
    CameraProvider,
    ConfigurationProvider,
    InputAction,
    PanelAdapter,
    PanelCapabilities,
    RegistrationProvider,
    WorkflowLaunch,
)
from .camera_health import (
    fetch_camera_health,
    normalize_camera_health,
    unavailable_camera_health,
)
from .catalog import (
    PANEL_CATALOG_SCHEMA_VERSION,
    checkbox_field,
    combobox_field,
    option,
    order_workflow_forms,
    select_field,
    standard_camera_controls,
    standard_core_workflows,
    standard_panel_product,
    text_field,
    validate_panel_catalog,
    validate_registration_submission,
    validate_workflow_submission,
)
from .document_store import DocumentKind, RepositoryDocumentStore
from .protocol import (
    InvalidEvent,
    PANEL_EVENT_SCHEMA_VERSION,
    ProgressEvent,
    announce_input,
    announce_progress,
    parse_event,
    strip_protocol_events,
)
from .process import WORKFLOW_STATUS_SCHEMA_VERSION
from .server import (
    OperatorPanelApplication,
    create_operator_panel_server,
    serve_operator_panel,
    serve_operator_panel_application,
)

__all__ = [
    "CameraProvider",
    "ConfigurationProvider",
    "DocumentKind",
    "InputAction",
    "InvalidEvent",
    "OperatorPanelApplication",
    "PANEL_CATALOG_SCHEMA_VERSION",
    "PANEL_EVENT_SCHEMA_VERSION",
    "PanelAdapter",
    "PanelCapabilities",
    "ProgressEvent",
    "RegistrationProvider",
    "RepositoryDocumentStore",
    "WorkflowLaunch",
    "WORKFLOW_STATUS_SCHEMA_VERSION",
    "announce_input",
    "announce_progress",
    "checkbox_field",
    "combobox_field",
    "create_operator_panel_server",
    "fetch_camera_health",
    "normalize_camera_health",
    "option",
    "order_workflow_forms",
    "parse_event",
    "serve_operator_panel",
    "serve_operator_panel_application",
    "select_field",
    "standard_camera_controls",
    "standard_core_workflows",
    "standard_panel_product",
    "strip_protocol_events",
    "text_field",
    "unavailable_camera_health",
    "validate_panel_catalog",
    "validate_registration_submission",
    "validate_workflow_submission",
]
