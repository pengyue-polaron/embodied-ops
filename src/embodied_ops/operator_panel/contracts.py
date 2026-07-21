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


class PanelAdapter(Protocol):
    """All repository-specific discovery, validation, and command building."""

    @property
    def repo_root(self) -> Path: ...

    def catalog(self) -> JsonObject: ...

    def camera_health(self) -> JsonObject: ...

    def build_launch(self, workflow: str, values: JsonObject) -> WorkflowLaunch: ...

    def config_template(self, payload: JsonObject) -> JsonObject: ...

    def validate_config(self, payload: JsonObject) -> JsonObject: ...

    def create_config(self, payload: JsonObject) -> JsonObject: ...

    def register(self, registration: str, values: JsonObject) -> JsonObject: ...
