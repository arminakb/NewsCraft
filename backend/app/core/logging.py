from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Literal

from uvicorn.logging import AccessFormatter

from app.core.redaction import (
    record_sanitizer_degradation,
    redact_request_target,
    redact_secrets,
    redact_string,
)

_DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_ACCESS_LOG_FORMAT = '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
_FORMAT_FAILED = "[LOG_FORMAT_FAILED]"
_LOGGER_CLASS_MARKER = "_newscraft_redacting_logger_class"
_LEGACY_FILTER_MARKER = "_newscraft_redacting_filter"
_TRUNCATED = "[TRUNCATED]"
_SAFE_LABEL = re.compile(r"[^A-Za-z0-9_.-]+")
_STANDARD_RECORD_KEYS = frozenset(
    logging.LogRecord(
        name="",
        level=0,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__
) | {"asctime", "message"}


def _clone_record(record: logging.LogRecord) -> logging.LogRecord:
    return logging.makeLogRecord(record.__dict__.copy())


def _safe_log_arguments(arguments: object) -> object:
    if isinstance(arguments, tuple):
        return tuple(redact_secrets(argument) for argument in arguments)
    if isinstance(arguments, Mapping):
        return redact_secrets(arguments)
    return redact_secrets(arguments)


def _render_safe_message(record: logging.LogRecord) -> None:
    message = record.msg if isinstance(record.msg, str) else redact_secrets(record.msg)
    record.msg = message
    record.args = _safe_log_arguments(record.args)  # type: ignore[assignment]
    rendered = record.getMessage()
    record.msg = redact_string(rendered)
    record.args = ()


def _render_safe_exception(record: logging.LogRecord) -> None:
    if record.exc_info is not None:
        try:
            exception_text = logging.Formatter().formatException(record.exc_info)
        except Exception as exc:
            # Exception only: a KeyboardInterrupt or SystemExit raised while
            # rendering a traceback belongs to the calling thread, not to this
            # formatter's fail-closed substitution.
            record_sanitizer_degradation("exception_render", exc)
            exception_text = "[Exception]"
        record.exc_text = redact_string(exception_text)
        record.exc_info = None
    elif record.exc_text:
        record.exc_text = redact_string(record.exc_text)
    if record.stack_info:
        record.stack_info = redact_string(record.stack_info)


def _redact_extras(record: logging.LogRecord) -> None:
    extras = {key: value for key, value in record.__dict__.items() if key not in _STANDARD_RECORD_KEYS}
    for key in extras:
        if isinstance(key, str):
            record.__dict__[key] = _TRUNCATED
        else:
            record.__dict__.pop(key, None)
    sanitized = redact_secrets(extras)
    if not isinstance(sanitized, Mapping):
        return
    for key, value in sanitized.items():
        if isinstance(key, str):
            record.__dict__[key] = value


def _sanitize_generic_record(record: logging.LogRecord) -> logging.LogRecord:
    cloned = _clone_record(record)
    _redact_extras(cloned)
    _render_safe_message(cloned)
    _render_safe_exception(cloned)
    return cloned


def _sanitize_access_record(record: logging.LogRecord) -> logging.LogRecord:
    cloned = _clone_record(record)
    _redact_extras(cloned)
    if not isinstance(cloned.msg, str):
        raise TypeError("access log message must be a string")
    if not isinstance(cloned.args, tuple) or len(cloned.args) != 5:
        raise ValueError("access log arguments must be a five-element tuple")
    client_addr, method, target, http_version, status_code = cloned.args
    if not all(isinstance(value, str) for value in (client_addr, method, target, http_version)):
        raise TypeError("access log string fields are invalid")
    if type(status_code) is not int:
        raise TypeError("access log status must be an integer")
    assert isinstance(client_addr, str)
    assert isinstance(method, str)
    assert isinstance(target, str)
    assert isinstance(http_version, str)
    cloned.msg = redact_string(cloned.msg)
    cloned.args = (
        redact_string(client_addr),
        redact_string(method),
        redact_request_target(target),
        redact_string(http_version),
        status_code,
    )
    _render_safe_exception(cloned)
    return cloned


def _safe_label(value: object, *, default: str) -> str:
    if not isinstance(value, str):
        return default
    redacted = redact_string(value)
    sanitized = _SAFE_LABEL.sub("_", redacted).strip("_")[:128]
    return sanitized or default


def _format_failed(record: logging.LogRecord, exc: BaseException) -> str:
    """Render the fail-closed substitute for a record that could not be formatted.

    The record's own content is never echoed — only its logger name, level, and
    the class of the exception that stopped the format. That class name is what
    separates "one hostile record" from "redaction is broken and every line is
    a sentinel", which the previous constant string made impossible to tell
    apart. ``record_sanitizer_degradation`` also counts it, so the second and
    later occurrences stay quiet.
    """

    try:
        logger_name = _safe_label(record.__dict__.get("name"), default="unknown")
        level_name = _safe_label(record.__dict__.get("levelname"), default="UNKNOWN")
    except BaseException:
        logger_name = "unknown"
        level_name = "UNKNOWN"
    try:
        error = record_sanitizer_degradation("log_format", exc)
    except BaseException:
        error = "Exception"
    return f"{_FORMAT_FAILED} logger={logger_name} level={level_name} error={error}"


class RedactingFormatter(logging.Formatter):
    """Format a sanitized clone of a generic record without touching the shared original."""

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        validate: bool = True,
        *,
        defaults: Mapping[str, object] | None = None,
        delegate: logging.Formatter | None = None,
    ) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt, style=style, validate=validate, defaults=defaults)
        self._delegate = delegate

    def format(self, record: logging.LogRecord) -> str:
        try:
            cloned = _sanitize_generic_record(record)
            if self._delegate is not None:
                return self._delegate.format(cloned)
            return super().format(cloned)
        except Exception as exc:
            # Exception, not BaseException: the sentinel is for records this
            # formatter cannot safely render, never for a KeyboardInterrupt or
            # SystemExit that belongs to whichever thread is logging.
            return _format_failed(record, exc)


class RedactingAccessFormatter(AccessFormatter):
    """Preserve Uvicorn's access tuple while formatting a sanitized record clone."""

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        use_colors: bool | None = None,
        *,
        delegate: logging.Formatter | None = None,
    ) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt, style=style, use_colors=use_colors)
        self._delegate = delegate

    def format(self, record: logging.LogRecord) -> str:
        try:
            cloned = _sanitize_access_record(record)
            if self._delegate is not None:
                return self._delegate.format(cloned)
            return super().format(cloned)
        except Exception as exc:
            # See RedactingFormatter.format: interpreter-level exits propagate.
            return _format_failed(record, exc)


def _configured_loggers() -> list[logging.Logger]:
    loggers = [logging.getLogger()]
    loggers.extend(
        logger for logger in logging.Logger.manager.loggerDict.values() if isinstance(logger, logging.Logger)
    )
    return loggers


def _configured_handlers(loggers: list[logging.Logger]) -> list[logging.Handler]:
    handlers: list[logging.Handler] = []
    identities: set[int] = set()
    for logger in loggers:
        for handler in logger.handlers:
            if id(handler) not in identities:
                handlers.append(handler)
                identities.add(id(handler))
    return handlers


def _install_generic_formatter(handler: logging.Handler) -> None:
    current = handler.formatter
    if isinstance(current, (RedactingFormatter, RedactingAccessFormatter)):
        return
    if current is None:
        handler.setFormatter(RedactingFormatter(_DEFAULT_LOG_FORMAT))
    else:
        handler.setFormatter(RedactingFormatter(delegate=current))


def _install_access_formatter(handler: logging.Handler) -> None:
    current = handler.formatter
    if isinstance(current, RedactingAccessFormatter):
        return
    if isinstance(current, AccessFormatter):
        handler.setFormatter(RedactingAccessFormatter(delegate=current))
    else:
        handler.setFormatter(RedactingAccessFormatter(fmt=_ACCESS_LOG_FORMAT, use_colors=False))


def _remove_legacy_filter(target: logging.Filterer) -> None:
    target.filters[:] = [item for item in target.filters if not getattr(item, _LEGACY_FILTER_MARKER, False)]


def _install_future_logger_class() -> type[logging.Logger]:
    logger_class = logging.getLoggerClass()
    if getattr(logger_class, _LOGGER_CLASS_MARKER, False):
        return logger_class

    class RedactingLogger(logger_class):  # type: ignore[valid-type, misc]
        _newscraft_redacting_logger_class = True

        def addHandler(self, handler: logging.Handler) -> None:
            if self.name == "uvicorn.access":
                _install_access_formatter(handler)
            else:
                _install_generic_formatter(handler)
            super().addHandler(handler)

        def __setattr__(self, name: str, value: object) -> None:
            if name == "handlers" and isinstance(value, list):
                logger_name = self.__dict__.get("name")
                for handler in value:
                    if not isinstance(handler, logging.Handler):
                        continue
                    if logger_name == "uvicorn.access":
                        _install_access_formatter(handler)
                    else:
                        _install_generic_formatter(handler)
            super().__setattr__(name, value)

    RedactingLogger.__name__ = f"Redacting{logger_class.__name__}"
    logging.setLoggerClass(RedactingLogger)
    return RedactingLogger


def configure_logging() -> None:
    """Install fail-closed clone-based formatters on app and Uvicorn handlers."""

    logging.basicConfig(level=logging.INFO, format=_DEFAULT_LOG_FORMAT)
    loggers = _configured_loggers()
    access_handler_ids = {id(handler) for handler in logging.getLogger("uvicorn.access").handlers}
    for logger in loggers:
        _remove_legacy_filter(logger)
    for handler in _configured_handlers(loggers):
        _remove_legacy_filter(handler)
        if id(handler) in access_handler_ids:
            _install_access_formatter(handler)
        else:
            _install_generic_formatter(handler)
    protected_logger_class = _install_future_logger_class()
    root = logging.getLogger()
    for logger in loggers:
        if logger is root or isinstance(logger, protected_logger_class):
            continue
        try:
            logger.__class__ = protected_logger_class
        except TypeError:
            # A third-party Logger subclass with a different memory layout is
            # still protected by every handler present at configuration time.
            continue
