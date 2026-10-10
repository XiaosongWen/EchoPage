"""Logging framework and timing utilities for EchoPage."""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Generator, Optional


def format_duration(seconds: float) -> str:
    """Format a duration in seconds into a human-readable string.

    Examples:
        format_duration(0.0005) -> "< 1ms"
        format_duration(0.45)   -> "450ms"
        format_duration(3.2)    -> "3.20s"
        format_duration(65.4)   -> "1m 5.4s"
        format_duration(3724)   -> "1h 2m 4s"
    """
    if seconds < 0:
        seconds = 0.0

    if seconds < 0.001:
        return "< 1ms"
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60.0:
        return f"{seconds:.2f}s"
    if seconds < 3600.0:
        minutes = int(seconds // 60)
        rem_seconds = seconds % 60
        return f"{minutes}m {rem_seconds:.1f}s"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    rem_seconds = seconds % 60
    return f"{hours}h {minutes}m {rem_seconds:.0f}s"


class EchoPageFormatter(logging.Formatter):
    """Custom formatter with timestamps, level padding, logger names, and optional ANSI color styling."""

    # ANSI Colors
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD_RED = "\033[1;31m"
    GRAY = "\033[90m"

    LEVEL_COLORS = {
        logging.DEBUG: GRAY,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    LEVEL_NAMES = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO ",
        logging.WARNING: "WARN ",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRIT ",
    }

    def __init__(self, use_color: Optional[bool] = None, datefmt: str = "%Y-%m-%d %H:%M:%S"):
        super().__init__(datefmt=datefmt)
        if use_color is None:
            # Enable colors if connected to a TTY and NO_COLOR environment variable is absent
            is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
            no_color = bool(os.getenv("NO_COLOR"))
            term = os.getenv("TERM", "")
            self.use_color = is_tty and not no_color and term != "dumb"
        else:
            self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        level_str = self.LEVEL_NAMES.get(record.levelno, record.levelname[:5].ljust(5))
        logger_name = record.name
        message = record.getMessage()

        if self.use_color:
            level_color = self.LEVEL_COLORS.get(record.levelno, self.RESET)
            # Example: [2026-10-10 14:45:00] [INFO ] [echopage.cli] Message...
            formatted = (
                f"{self.CYAN}[{timestamp}]{self.RESET} "
                f"{level_color}[{level_str}]{self.RESET} "
                f"{self.MAGENTA}[{logger_name}]{self.RESET} "
                f"{message}"
            )
        else:
            formatted = f"[{timestamp}] [{level_str}] [{logger_name}] {message}"

        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                formatted = f"{formatted}\n{record.exc_text}"

        return formatted


class TimedStepContext:
    """Helper object passed into timed_step blocks allowing additional context."""

    def __init__(self, action: str):
        self.action = action
        self.start_time = time.perf_counter()
        self.elapsed: float = 0.0
        self.detail: Optional[str] = None

    def set_detail(self, detail: str) -> None:
        """Set additional descriptive detail for the finished log."""
        self.detail = detail


@contextmanager
def timed_step(
    logger: logging.Logger,
    action: str,
    level: int = logging.INFO,
    log_start: bool = True,
) -> Generator[TimedStepContext, None, None]:
    """Context manager to measure and log execution duration for a step.

    Parameters
    ----------
    logger : logging.Logger
        Logger instance to emit logs to.
    action : str
        Human-readable action description.
    level : int, default logging.INFO
        Logging level.
    log_start : bool, default True
        Whether to log the start of the action.
    """
    ctx = TimedStepContext(action)
    if log_start:
        logger.log(level, "%s started...", action)

    try:
        yield ctx
        ctx.elapsed = time.perf_counter() - ctx.start_time
        detail_suffix = f" - {ctx.detail}" if ctx.detail else ""
        logger.log(
            level,
            "%s completed (took %s)%s",
            action,
            format_duration(ctx.elapsed),
            detail_suffix,
        )
    except Exception as exc:
        ctx.elapsed = time.perf_counter() - ctx.start_time
        logger.error(
            "%s failed after %s: %s",
            action,
            format_duration(ctx.elapsed),
            exc,
        )
        raise


class _DynamicStream:
    """Stream wrapper delegating to sys.stdout at emit time, allowing pytest capsys capture."""

    def __init__(self, target_stream=None):
        self._target_stream = target_stream

    @property
    def _stream(self):
        return self._target_stream if self._target_stream is not None else sys.stdout

    def write(self, s: str):
        return self._stream.write(s)

    def flush(self):
        return self._stream.flush()

    def isatty(self) -> bool:
        return hasattr(self._stream, "isatty") and self._stream.isatty()


def setup_logging(
    level: Optional[int] = None,
    verbose: bool = False,
    stream: Optional[object] = None,
    use_color: Optional[bool] = None,
) -> logging.Logger:
    """Configure EchoPage unified logging format across the entire application."""
    if level is None:
        level = logging.DEBUG if verbose else logging.INFO

    out_stream = _DynamicStream(stream)

    root_logger = logging.getLogger()
    echopage_logger = logging.getLogger("echopage")

    formatter = EchoPageFormatter(use_color=use_color)
    handler = logging.StreamHandler(out_stream)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    # Remove existing handlers to avoid duplicate lines
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    for h in list(echopage_logger.handlers):
        echopage_logger.removeHandler(h)

    echopage_logger.setLevel(level)
    echopage_logger.propagate = True

    # Set root logger handler so all namespaced and un-namespaced loggers emit once
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Silence chatty third-party loggers (keep urllib3 unmuted for telemetry visibility)
    quiet_loggers = [
        "torio",
        "matplotlib",
        "numba",
        "filelock",
        "huggingface_hub",
        "transformers",
        "pyannote",
        "torch",
    ]
    for q in quiet_loggers:
        logging.getLogger(q).setLevel(logging.WARNING)

    return echopage_logger
