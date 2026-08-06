"""Dependency-free terminal presentation for embodied operator workflows."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from enum import Enum
from typing import TextIO


class Tone(str, Enum):
    INFO = "1;34"
    STEP = "1;36"
    SUCCESS = "1;32"
    WARNING = "1;33"
    FAILURE = "1;31"


LEVEL_TONES = {
    "INFO": Tone.INFO,
    "STEP": Tone.STEP,
    "PASS": Tone.SUCCESS,
    "WARN": Tone.WARNING,
    "FAIL": Tone.FAILURE,
}


def color_enabled(stream: TextIO | None = None) -> bool:
    """Honor ``NO_COLOR`` and never color redirected output."""

    output = stream or sys.stdout
    return not os.environ.get("NO_COLOR") and output.isatty()


def style(text: str, tone: Tone, *, stream: TextIO | None = None) -> str:
    if not color_enabled(stream):
        return text
    return f"\033[{tone.value}m{text}\033[0m"


def label(level: str, *, stream: TextIO | None = None) -> str:
    normalized = level.upper()
    tone = LEVEL_TONES.get(normalized, Tone.INFO)
    return style(f"[{normalized}]", tone, stream=stream)


def padded_label(level: str, *, width: int = 6, stream: TextIO | None = None) -> str:
    normalized = level.upper()
    tone = LEVEL_TONES.get(normalized, Tone.INFO)
    return style(f"[{normalized}]".ljust(width), tone, stream=stream)


def emit(
    level: str,
    message: str,
    *,
    stream: TextIO | None = None,
    flush: bool = True,
) -> None:
    output = stream or sys.stdout
    print(f"{label(level, stream=output)} {message}", file=output, flush=flush)


def info(message: str, *, flush: bool = True) -> None:
    emit("INFO", message, flush=flush)


def step(message: str, *, flush: bool = True) -> None:
    emit("STEP", message, flush=flush)


def success(message: str, *, flush: bool = True) -> None:
    emit("PASS", message, flush=flush)


def warning(message: str, *, flush: bool = True) -> None:
    emit("WARN", message, stream=sys.stderr, flush=flush)


def failure(message: str, *, flush: bool = True) -> None:
    emit("FAIL", message, stream=sys.stderr, flush=flush)


class LiveStatusLine:
    """Render one replace-in-place status line, throttling redirected output."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        redirected_interval_s: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if redirected_interval_s <= 0:
            raise ValueError("redirected status interval must be positive")
        self.stream = stream or sys.stdout
        self.redirected_interval_s = redirected_interval_s
        self.monotonic = monotonic
        self._tty = self.stream.isatty()
        self._visible_width = 0
        self._last_redirected_at: float | None = None

    def update(self, message: str, *, force: bool = False) -> None:
        rendered = f"[RUN] {message}"
        if self._tty:
            padding = " " * max(0, self._visible_width - len(rendered))
            self.stream.write(f"\r{rendered}{padding}")
            self.stream.flush()
            self._visible_width = len(rendered)
            return
        now = self.monotonic()
        if (
            force
            or self._last_redirected_at is None
            or now - self._last_redirected_at >= self.redirected_interval_s
        ):
            print(rendered, file=self.stream, flush=True)
            self._last_redirected_at = now

    def break_line(self) -> None:
        if not self._tty or self._visible_width <= 0:
            return
        self.stream.write("\r" + (" " * self._visible_width) + "\r")
        self.stream.flush()
        self._visible_width = 0

    def close(self) -> None:
        self.break_line()


class ArgumentParser(argparse.ArgumentParser):
    """Argparse with the standard embodied-ops failure presentation."""

    def print_usage(self, file: TextIO | None = None) -> None:
        stream = file or sys.stdout
        print(_styled_help(self.format_usage(), stream), end="", file=stream)

    def print_help(self, file: TextIO | None = None) -> None:
        stream = file or sys.stdout
        print(_styled_help(self.format_help(), stream), end="", file=stream)

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        failure(message)
        raise SystemExit(2)


def _styled_help(value: str, stream: TextIO) -> str:
    lines: list[str] = []
    for line in value.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        suffix = line[len(stripped) :]
        if stripped.startswith("usage:"):
            stripped = style("usage:", Tone.INFO, stream=stream) + stripped[6:]
        elif stripped and not stripped.startswith(" ") and stripped.endswith(":"):
            stripped = style(stripped, Tone.INFO, stream=stream)
        lines.append(stripped + suffix)
    return "".join(lines)
