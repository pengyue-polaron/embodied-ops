import hashlib
import json
import re
import zipfile
from pathlib import Path

from embodied_ops.foxglove_publish import (
    ExtensionManifest,
    FoxgloveApiError,
    normalize_extension_archive,
    publish_assets,
    read_extension_manifest,
)
from embodied_ops.teleop.foxglove_bridge import SERVICE_COMMANDS


def make_extension(path: Path, *, version: str = "1.0.0") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "package.json",
            json.dumps(
                {
                    "publisher": "pengyue-robotics",
                    "name": "quest-teleop-controls",
                    "version": version,
                    "displayName": "Quest Teleop Controls",
                }
            ),
        )
    return path


class FakeApi:
    def __init__(self, *, conflict: bool = False) -> None:
        self.conflict = conflict
        self.layout_data = None
        self.extension_sha256 = ""

    def upload_extension(self, extension: Path) -> dict:
        self.extension_sha256 = hashlib.sha256(extension.read_bytes()).hexdigest()
        if self.conflict:
            raise FoxgloveApiError(409, "already published")
        return {"id": "ext_123"}

    def list_extensions(self) -> list[dict]:
        return [
            {
                "id": "ext_123",
                "publisher": "pengyue-robotics",
                "name": "quest-teleop-controls",
                "activeVersion": "1.0.0",
                "sha256Sum": self.extension_sha256,
            }
        ]

    def update_layout(self, layout_id: str, *, name: str, data: dict) -> dict:
        assert name == "Unit Teleop"
        self.layout_data = data
        return {"id": layout_id, "updatedAt": "2026-09-02T12:00:00Z"}

    def get_layout(self, layout_id: str) -> dict:
        assert layout_id == "lay_test"
        return {"data": self.layout_data}


def test_reads_foxe_manifest(tmp_path: Path) -> None:
    extension = make_extension(tmp_path / "controls.foxe")
    assert read_extension_manifest(extension) == ExtensionManifest(
        publisher="pengyue-robotics",
        name="quest-teleop-controls",
        version="1.0.0",
        display_name="Quest Teleop Controls",
    )


def test_normalizes_equivalent_foxe_archives_to_identical_bytes(tmp_path: Path) -> None:
    first = make_extension(tmp_path / "first.foxe")
    second = make_extension(tmp_path / "second.foxe")
    with zipfile.ZipFile(second, "a") as archive:
        archive.writestr(
            zipfile.ZipInfo("dist/", date_time=(2026, 9, 3, 12, 34, 56)),
            b"",
        )
    with zipfile.ZipFile(first, "a") as archive:
        archive.writestr(
            zipfile.ZipInfo("dist/", date_time=(2025, 1, 2, 3, 4, 6)),
            b"",
        )

    normalize_extension_archive(first)
    normalize_extension_archive(second)

    assert first.read_bytes() == second.read_bytes()


def test_publishes_extension_before_layout_and_verifies_both(tmp_path: Path) -> None:
    extension = make_extension(tmp_path / "controls.foxe")
    layout = tmp_path / "layout.json"
    layout.write_text('{"layout":{"direction":"row"}}', encoding="utf-8")
    api = FakeApi()

    result = publish_assets(
        api,
        extension=extension,
        layout=layout,
        layout_id="lay_test",
        layout_name="Unit Teleop",
    )

    assert result.extension_id == "ext_123"
    assert result.layout_id == "lay_test"
    assert api.layout_data == {"layout": {"direction": "row"}}


def test_repeated_publish_accepts_the_same_active_version(tmp_path: Path) -> None:
    extension = make_extension(tmp_path / "controls.foxe")
    layout = tmp_path / "layout.json"
    layout.write_text("{}", encoding="utf-8")

    result = publish_assets(
        FakeApi(conflict=True),
        extension=extension,
        layout=layout,
        layout_id="lay_test",
        layout_name="Unit Teleop",
    )

    assert result.extension_version == "1.0.0"


def test_shared_extension_can_publish_without_a_backend_layout(tmp_path: Path) -> None:
    extension = make_extension(tmp_path / "controls.foxe")

    result = publish_assets(FakeApi(), extension=extension)

    assert result.extension_id == "ext_123"
    assert result.layout_id is None


def test_react_panel_exposes_every_bridge_service() -> None:
    panel = (
        Path(__file__).parents[1]
        / "foxglove"
        / "quest-teleop-controls"
        / "src"
        / "TeleopControls.tsx"
    ).read_text(encoding="utf-8")
    panel_services = set(re.findall(r'service: "([^"]+)"', panel))

    assert panel_services == set(SERVICE_COMMANDS)
