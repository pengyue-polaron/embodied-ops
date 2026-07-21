"""Small adapter contract between the reusable panel and one repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class InputAction:
    action_id: str
    label: str
    line: str
    tone: str = "default"


@dataclass(frozen=True)
class WorkflowLaunch:
    workflow: str
    name: str
    command: tuple[str, ...]
    input_actions: tuple[InputAction, ...] = ()


class CameraProvider(Protocol):
    def camera_health(self) -> JsonObject: ...


class ConfigurationProvider(Protocol):
    def config_template(self, payload: JsonObject) -> JsonObject: ...

    def validate_config(self, payload: JsonObject) -> JsonObject: ...

    def create_config(self, payload: JsonObject) -> JsonObject: ...


class RegistrationProvider(Protocol):
    def register(self, registration: str, values: JsonObject) -> JsonObject: ...


@dataclass(frozen=True)
class PanelCapabilities:
    camera: CameraProvider | None = None
    configuration: ConfigurationProvider | None = None
    registration: RegistrationProvider | None = None


class PanelAdapter(Protocol):
    """Minimal repository integration for catalog and workflow launches."""

    @property
    def repo_root(self) -> Path: ...

    @property
    def capabilities(self) -> PanelCapabilities: ...

    def catalog(self) -> JsonObject: ...

    def build_launch(self, workflow: str, values: JsonObject) -> WorkflowLaunch: ...
