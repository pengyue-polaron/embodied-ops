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
    "PanelAdapter",
    "PanelCapabilities",
    "ProgressEvent",
    "RegistrationProvider",
    "RepositoryDocumentStore",
    "WorkflowLaunch",
    "announce_input",
    "announce_progress",
    "fetch_camera_health",
    "normalize_camera_health",
    "parse_event",
    "serve_operator_panel",
    "strip_protocol_events",
    "unavailable_camera_health",
]
