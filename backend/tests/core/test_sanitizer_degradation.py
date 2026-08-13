"""Fail-closed sanitization must stay fail-closed, and must stay diagnosable.

The redaction helpers and the log formatters both substitute a placeholder when
inspecting a value raises. That is the right call — an unrenderable value must
never be echoed — but it used to leave no record at all, so a redaction bug that
degraded every log line looked exactly like a quiet system. These tests pin the
two properties that fix buys: interpreter-level exits are no longer absorbed,
and every degradation is counted and named by exception class (never by value).
"""

import logging

import pytest

from app.core.logging import RedactingAccessFormatter, RedactingFormatter
from app.core.redaction import (
    record_sanitizer_degradation,
    redact_secrets,
    reset_sanitizer_degradation_counts,
    sanitizer_degradation_counts,
)

ACCESS_FORMAT = '%(client_addr)s - "%(request_line)s" %(status_code)s'


@pytest.fixture(autouse=True)
def _clean_counts():
    reset_sanitizer_degradation_counts()
    yield
    reset_sanitizer_degradation_counts()


class _ExitingFormatter(logging.Formatter):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self._error = error

    def format(self, record: logging.LogRecord) -> str:
        raise self._error


def _generic_record() -> logging.LogRecord:
    return logging.LogRecord("newscraft.degradation", logging.WARNING, "<test>", 1, "message", (), None)


def _access_record() -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "<test>",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/health", "1.1", 200),
        None,
    )


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(2)])
def test_generic_formatter_lets_interpreter_exits_propagate(error: BaseException) -> None:
    formatter = RedactingFormatter(delegate=_ExitingFormatter(error))

    with pytest.raises(type(error)):
        formatter.format(_generic_record())


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(2)])
def test_access_formatter_lets_interpreter_exits_propagate(error: BaseException) -> None:
    formatter = RedactingAccessFormatter(fmt=ACCESS_FORMAT, use_colors=False, delegate=_ExitingFormatter(error))

    with pytest.raises(type(error)):
        formatter.format(_access_record())


def test_format_failure_is_counted_and_named_by_exception_class() -> None:
    formatter = RedactingFormatter(delegate=_ExitingFormatter(RuntimeError("boom")))

    rendered = formatter.format(_generic_record())

    assert rendered.endswith(" error=RuntimeError")
    assert sanitizer_degradation_counts()[("log_format", "RuntimeError")] == 1


class _HostileMapping(dict):
    def items(self):
        raise ValueError("mapping traversal exploded")


def test_redaction_degradation_is_counted_without_naming_the_value() -> None:
    rendered = redact_secrets(_HostileMapping({"password": "redaction-count-canary"}))

    assert rendered == "[_HostileMapping]"
    assert "redaction-count-canary" not in str(rendered)
    assert sanitizer_degradation_counts()[("mapping_traversal", "ValueError")] == 1


def test_only_the_first_occurrence_of_each_kind_reaches_stderr(capsys) -> None:
    for _ in range(5):
        record_sanitizer_degradation("unit_scope", ValueError("x"))
    record_sanitizer_degradation("unit_scope", TypeError("y"))

    captured = capsys.readouterr().err
    assert captured.count("[REDACTION_DEGRADED] scope=unit_scope error=ValueError") == 1
    assert captured.count("[REDACTION_DEGRADED] scope=unit_scope error=TypeError") == 1
    assert sanitizer_degradation_counts()[("unit_scope", "ValueError")] == 5


def test_hostile_exception_class_names_are_sanitized() -> None:
    class _Meta(type):
        @property
        def __name__(cls) -> str:  # type: ignore[override]
            return "Bad Name\nwith newline"

    class _Hostile(Exception, metaclass=_Meta):
        pass

    label = record_sanitizer_degradation("unit_scope", _Hostile())

    assert "\n" not in label
    assert label == "Bad_Name_with_newline"
