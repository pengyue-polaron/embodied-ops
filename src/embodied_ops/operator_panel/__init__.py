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
    select_field,
    text_field,
    validate_panel_catalog,
)
from .document_store import DocumentKind, RepositoryDocumentStore
from .protocol import (
    InvalidEvent,
    ProgressEvent,
    announce_input,
    announce_progress,
    parse_event,
    strip_protocol_events,
)
from .server import OperatorPanelApplication, serve_operator_panel

__all__ = [
    "CameraProvider",
    "ConfigurationProvider",
    "DocumentKind",
    "InputAction",
    "InvalidEvent",
    "OperatorPanelApplication",
    "PANEL_CATALOG_SCHEMA_VERSION",
    "PanelAdapter",
    "PanelCapabilities",
    "ProgressEvent",
    "RegistrationProvider",
    "RepositoryDocumentStore",
    "WorkflowLaunch",
    "announce_input",
    "announce_progress",
    "checkbox_field",
    "combobox_field",
    "fetch_camera_health",
    "normalize_camera_health",
    "option",
    "parse_event",
    "serve_operator_panel",
    "select_field",
    "strip_protocol_events",
    "text_field",
    "unavailable_camera_health",
    "validate_panel_catalog",
]
