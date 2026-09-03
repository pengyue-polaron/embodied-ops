from __future__ import annotations

import http.server
import threading

from embodied_ops.teleop.foxglove_bridge import FoxgloveTeleopBridge
from embodied_ops.teleop.foxglove_probe import is_foxglove_server_ready


class _QuietHttpHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, _format: str, *args: object) -> None:
        return


def test_probe_accepts_foxglove_server_info() -> None:
    bridge = FoxgloveTeleopBridge(
        target_endpoint="inproc://probe-test-target",
        feedback_endpoint="inproc://probe-test-feedback",
        command_endpoint="inproc://probe-test-command",
        host="127.0.0.1",
        port=0,
    )
    try:
        assert is_foxglove_server_ready(f"ws://127.0.0.1:{bridge.port}", timeout_sec=2.0)
    finally:
        bridge.close()


def test_probe_rejects_plain_http_listener() -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _QuietHttpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert not is_foxglove_server_ready(f"ws://127.0.0.1:{server.server_port}", timeout_sec=0.5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)
