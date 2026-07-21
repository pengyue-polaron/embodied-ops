"""Dependency-free HTTP server for an adapter-driven operator panel."""

from __future__ import annotations

import hmac
import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .contracts import JsonObject, PanelAdapter
from .process import WorkflowProcess


ASSET_ROOT = Path(__file__).with_name("assets")
MAX_REQUEST_BYTES = 256 * 1024


class OperatorPanelApplication:
    def __init__(self, adapter: PanelAdapter) -> None:
        self.adapter = adapter
        self.token = secrets.token_urlsafe(32)
        self.workflow = WorkflowProcess(Path(adapter.repo_root))

    def camera_health(self) -> JsonObject:
        provider = self.adapter.capabilities.camera
        if provider is None:
            raise _CapabilityUnavailable("camera")
        return provider.camera_health()

    def start(self, payload: JsonObject) -> JsonObject:
        workflow = payload.get("workflow")
        values = payload.get("values", {})
        if not isinstance(workflow, str) or not isinstance(values, dict):
            raise ValueError("start requires workflow and values")
        return self.workflow.start(self.adapter.build_launch(workflow, values))

    def create_config(self, payload: JsonObject) -> JsonObject:
        provider = self.adapter.capabilities.configuration
        if provider is None:
            raise _CapabilityUnavailable("configuration")
        if self.workflow.snapshot()["active"]:
            raise RuntimeError("cannot create a configuration while a workflow is active")
        result = provider.create_config(payload)
        return {**result, "catalog": self.adapter.catalog()}

    def config_template(self, payload: JsonObject) -> JsonObject:
        provider = self.adapter.capabilities.configuration
        if provider is None:
            raise _CapabilityUnavailable("configuration")
        return provider.config_template(payload)

    def validate_config(self, payload: JsonObject) -> JsonObject:
        provider = self.adapter.capabilities.configuration
        if provider is None:
            raise _CapabilityUnavailable("configuration")
        return provider.validate_config(payload)

    def register(self, payload: JsonObject) -> JsonObject:
        provider = self.adapter.capabilities.registration
        if provider is None:
            raise _CapabilityUnavailable("registration")
        if self.workflow.snapshot()["active"]:
            raise RuntimeError("cannot register repository data while a workflow is active")
        registration = payload.get("registration")
        values = payload.get("values", {})
        if not isinstance(registration, str) or not isinstance(values, dict):
            raise ValueError("register requires a registration id and values")
        result = provider.register(registration, values)
        return {**result, "catalog": self.adapter.catalog()}


class _CapabilityUnavailable(LookupError):
    pass


def serve_operator_panel(
    adapter: PanelAdapter,
    *,
    bind: str = "127.0.0.1",
    port: int = 8765,
    asset_root: Path = ASSET_ROOT,
) -> int:
    app = OperatorPanelApplication(adapter)
    handler = _handler_type(app, asset_root.resolve())
    server = ThreadingHTTPServer((bind, port), handler)
    server.daemon_threads = True
    print("[INFO] Operator Panel is adapter-driven.", flush=True)
    if bind == "0.0.0.0":
        print(f"[PASS] Operator Panel local: http://127.0.0.1:{port}", flush=True)
        print(
            f"[WARN] Operator Panel LAN: http://<this-host-ip>:{port} (trusted LAN only)",
            flush=True,
        )
    else:
        print(f"[PASS] Operator Panel: http://{bind}:{port}", flush=True)
    try:
        while True:
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                if not app.workflow.snapshot()["active"]:
                    break
                try:
                    app.workflow.stop()
                except RuntimeError as exc:
                    print(f"[FAIL] {exc}; panel remains available.", flush=True)
                    continue
                break
    finally:
        server.server_close()
    return 0


def _handler_type(app: OperatorPanelApplication, asset_root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "OperatorPanel/1"

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/":
                body = (asset_root / "index.html").read_text().replace("__PANEL_TOKEN__", app.token)
                self._send_bytes(
                    HTTPStatus.OK,
                    body.encode(),
                    "text/html; charset=utf-8",
                    content_security_policy=True,
                )
                return
            if path == "/panel.css":
                self._send_asset("panel.css", "text/css; charset=utf-8")
                return
            if path == "/panel.js":
                self._send_asset("panel.js", "text/javascript; charset=utf-8")
                return
            if path == "/api/catalog":
                self._send_json(HTTPStatus.OK, app.adapter.catalog())
                return
            if path == "/api/camera-health":
                try:
                    payload = app.camera_health()
                except _CapabilityUnavailable:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                self._send_json(HTTPStatus.OK, payload)
                return
            if path == "/api/status":
                self._send_json(HTTPStatus.OK, app.workflow.snapshot())
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not hmac.compare_digest(self.headers.get("X-Operator-Panel-Token", ""), app.token):
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "invalid token"})
                return
            try:
                payload = self._read_json()
                path = urlsplit(self.path).path
                if path == "/api/start":
                    result = app.start(payload)
                elif path == "/api/input":
                    result = app.workflow.send(str(payload.get("action", "")))
                elif path == "/api/stop":
                    result = app.workflow.stop()
                elif path == "/api/config/template":
                    result = app.config_template(payload)
                elif path == "/api/config/validate":
                    result = app.validate_config(payload)
                elif path == "/api/config/create":
                    result = app.create_config(payload)
                elif path == "/api/register":
                    result = app.register(payload)
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
            except (ValueError, FileNotFoundError, FileExistsError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except _CapabilityUnavailable:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            except RuntimeError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, result)

        def _read_json(self) -> JsonObject:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid content length") from exc
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _send_asset(self, filename: str, content_type: str) -> None:
            self._send_bytes(
                HTTPStatus.OK,
                (asset_root / filename).read_bytes(),
                content_type,
            )

        def _send_json(self, status: HTTPStatus, payload: Any) -> None:
            self._send_bytes(
                status,
                json.dumps(payload, ensure_ascii=False).encode(),
                "application/json; charset=utf-8",
            )

        def _send_bytes(
            self,
            status: HTTPStatus,
            body: bytes,
            content_type: str,
            *,
            content_security_policy: bool = False,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            if content_security_policy:
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; img-src 'self' http:; "
                    "script-src 'self'; style-src 'self'; connect-src 'self'; "
                    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                )
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return Handler
