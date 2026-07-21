"""Adapter-driven Web operations for embodied-AI repositories."""

from .config_store import ConfigKind, RepositoryConfigStore
from .contracts import InputAction, PanelAdapter, WorkflowLaunch
from .protocol import (
    PROTOCOL_PREFIX,
    InvalidEvent,
    ProgressEvent,
    announce_input,
    announce_progress,
    parse_event,
)
from .server import OperatorPanelApplication, serve_operator_panel

__all__ = [
    "ConfigKind",
    "InputAction",
    "InvalidEvent",
    "OperatorPanelApplication",
    "PanelAdapter",
    "ProgressEvent",
    "PROTOCOL_PREFIX",
    "RepositoryConfigStore",
    "WorkflowLaunch",
    "announce_input",
    "announce_progress",
    "parse_event",
    "serve_operator_panel",
]
