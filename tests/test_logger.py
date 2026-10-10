"""Unit tests for EchoPage logging and timing framework."""

import logging
import io
import time
import pytest

from echopage.logger import (
    EchoPageFormatter,
    format_duration,
    setup_logging,
    timed_step,
)


def test_format_duration_sub_millisecond():
    assert format_duration(0.0001) == "< 1ms"
    assert format_duration(0.0) == "< 1ms"
    assert format_duration(-5.0) == "< 1ms"


def test_format_duration_milliseconds():
    assert format_duration(0.005) == "5ms"
    assert format_duration(0.350) == "350ms"
    assert format_duration(0.999) == "999ms"


def test_format_duration_seconds():
    assert format_duration(1.0) == "1.00s"
    assert format_duration(15.234) == "15.23s"
    assert format_duration(59.99) == "59.99s"


def test_format_duration_minutes():
    assert format_duration(60.0) == "1m 0.0s"
    assert format_duration(125.5) == "2m 5.5s"
    assert format_duration(3599.0) == "59m 59.0s"


def test_format_duration_hours():
    assert format_duration(3600.0) == "1h 0m 0s"
    assert format_duration(3665.0) == "1h 1m 5s"
    assert format_duration(7325.0) == "2h 2m 5s"


def test_echopage_formatter_plain():
    formatter = EchoPageFormatter(use_color=False, datefmt="%Y-%m-%d %H:%M:%S")
    record = logging.LogRecord(
        name="echopage.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Test message %d",
        args=(123,),
        exc_info=None,
    )
    output = formatter.format(record)
    assert "[INFO ]" in output
    assert "[echopage.test]" in output
    assert "Test message 123" in output
    assert "\033[" not in output  # No ANSI escapes


def test_echopage_formatter_with_color():
    formatter = EchoPageFormatter(use_color=True, datefmt="%Y-%m-%d %H:%M:%S")
    record = logging.LogRecord(
        name="echopage.cli",
        level=logging.ERROR,
        pathname=__file__,
        lineno=20,
        msg="Error occurred",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    assert "\033[" in output  # Has ANSI color escapes
    assert "ERROR" in output
    assert "Error occurred" in output


def test_echopage_formatter_exception_traceback():
    formatter = EchoPageFormatter(use_color=False)
    try:
        raise ValueError("Sample error")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="echopage.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=30,
        msg="An error happened",
        args=(),
        exc_info=exc_info,
    )
    output = formatter.format(record)
    assert "ValueError: Sample error" in output
    assert "Traceback" in output


def test_timed_step_success():
    stream = io.StringIO()
    logger = logging.getLogger("test_timed_step")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False

    with timed_step(logger, "Data processing") as step:
        time.sleep(0.01)
        step.set_detail("processed 10 items")

    log_output = stream.getvalue()
    assert "Data processing started..." in log_output
    assert "Data processing completed (took " in log_output
    assert "- processed 10 items" in log_output
    assert step.elapsed >= 0.005


def test_timed_step_failure():
    stream = io.StringIO()
    logger = logging.getLogger("test_timed_step_fail")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False

    with pytest.raises(RuntimeError, match="Boom"):
        with timed_step(logger, "Failing step"):
            raise RuntimeError("Boom")

    log_output = stream.getvalue()
    assert "Failing step started..." in log_output
    assert "Failing step failed after " in log_output
    assert "Boom" in log_output


def test_setup_logging():
    stream = io.StringIO()
    logger = setup_logging(verbose=True, stream=stream, use_color=False)
    assert logger.level == logging.DEBUG

    logger.debug("Debug test message")
    logger.info("Info test message")

    output = stream.getvalue()
    assert "[DEBUG]" in output
    assert "Debug test message" in output
    assert "[INFO ]" in output
    assert "Info test message" in output

    # Restore default stream
    setup_logging(stream=None)

