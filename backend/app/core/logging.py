from __future__ import annotations

import logging
from collections.abc import Mapping

from app.core.redaction import redact_secrets, redact_string

_FILTER_MARKER = "_newscraft_redacting_filter"
_LOGGER_CLASS_MARKER = "_newscraft_redacting_logger_class"
_TRUNCATED = "[TRUNCATED]"
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


def _safe_log_arguments(arguments: object) -> object:
    if isinstance(arguments, tuple):
        return tuple(redact_secrets(argument) for argument in arguments)
    if isinstance(arguments, Mapping):
        return redact_secrets(arguments)
    return redact_secrets(arguments)


def _render_safe_message(record: logging.LogRecord) -> str:
    message = record.msg
    if not isinstance(message, str):
        message = redact_secrets(message)
    arguments = _safe_log_arguments(record.args)
    record.msg = message
    record.args = arguments  # type: ignore[assignment]
    try:
        rendered = record.getMessage()
    except Exception:
        rendered = f"{message} {arguments}"
    record.msg = redact_string(rendered)
    record.args = ()
    return str(record.msg)


def _render_safe_exception(record: logging.LogRecord) -> None:
    if record.exc_info is not None:
        try:
            exception_text = logging.Formatter().formatException(record.exc_info)
        except Exception:
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


class _RedactingFilter(logging.Filter):
    _newscraft_redacting_filter = True

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            _redact_extras(record)
            _render_safe_message(record)
            _render_safe_exception(record)
        except Exception:
            _redact_extras(record)
            record.msg = "[LOG_REDACTION_FAILED]"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


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


def _ensure_redacting_filter(target: logging.Filterer) -> None:
    if not any(getattr(item, _FILTER_MARKER, False) for item in target.filters):
        target.addFilter(_RedactingFilter())


def _install_future_logger_class() -> None:
    logger_class = logging.getLoggerClass()
    if getattr(logger_class, _LOGGER_CLASS_MARKER, False):
        return

    class RedactingLogger(logger_class):  # type: ignore[valid-type, misc]
        _newscraft_redacting_logger_class = True

        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            _ensure_redacting_filter(self)

    RedactingLogger.__name__ = f"Redacting{logger_class.__name__}"
    logging.setLoggerClass(RedactingLogger)


def configure_logging() -> None:
    """Configure application logging and sanitize every configured handler."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    loggers = _configured_loggers()
    for logger in loggers:
        _ensure_redacting_filter(logger)
    for handler in _configured_handlers(loggers):
        _ensure_redacting_filter(handler)
    _install_future_logger_class()
