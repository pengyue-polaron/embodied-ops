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
    "parse_event",
    "serve_operator_panel",
    "strip_protocol_events",
]
