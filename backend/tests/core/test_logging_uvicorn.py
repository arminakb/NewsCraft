from __future__ import annotations

import asyncio
import copy
import io
import logging
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
from fastapi import FastAPI
from uvicorn import Config, Server
from uvicorn.config import LOGGING_CONFIG
from uvicorn.logging import AccessFormatter

from app.core.logging import RedactingAccessFormatter, RedactingFormatter, configure_logging

ACCESS_FORMAT = '%(client_addr)s - "%(request_line)s" %(status_code)s'
FORMAT_FAILED = "[LOG_FORMAT_FAILED] logger=uvicorn.access level=INFO"


def _access_record(
    *,
    target: str = "/health?token=access-query-canary&safe=yes",
    status_code: object = 200,
    args: object | None = None,
) -> logging.LogRecord:
    access_args = (
        "127.0.0.1:43100",
        "GET",
        target,
        "1.1",
        status_code,
    )
    if args is not None:
        access_args = args
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "<phase5-test>",
        1,
        '%s - "%s %s HTTP/%s" %d',
        access_args,  # type: ignore[arg-type]
        None,
    )


class HostileString:
    def __str__(self) -> str:
        raise AssertionError("password=hostile-str-canary")


class ExplodingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        raise RuntimeError(f"api_key=delegate-canary record={record.name}")


@contextmanager
def _preserve_logging_state(*names: str) -> Iterator[None]:
    root = logging.getLogger()
    loggers = [logging.getLogger(name) for name in names]
    root_state = (list(root.handlers), root.level, list(root.filters), root.disabled)
    logger_states = {
        logger: (
            list(logger.handlers),
            logger.level,
            logger.propagate,
            list(logger.filters),
            logger.disabled,
        )
        for logger in loggers
    }
    logger_class = logging.getLoggerClass()
    try:
        yield
    finally:
        root.handlers, root.level, root.filters, root.disabled = root_state
        for logger, state in logger_states.items():
            logger.handlers, logger.level, logger.propagate, logger.filters, logger.disabled = state
        logging.setLoggerClass(logger_class)


def test_real_uvicorn_access_formatter_contract_is_preserved_without_record_mutation() -> None:
    formatter = RedactingAccessFormatter(fmt=ACCESS_FORMAT, use_colors=False)
    record = _access_record()
    original_args = record.args
    original_dict = record.__dict__.copy()

    rendered = formatter.format(record)

    assert isinstance(formatter, AccessFormatter)
    assert "127.0.0.1:43100" in rendered
    assert "GET /health?token=%5BREDACTED%5D&safe=yes HTTP/1.1" in rendered
    assert "200 OK" in rendered
    assert "access-query-canary" not in rendered
    assert record.args is original_args
    assert record.__dict__ == original_dict
    assert "request_line" not in record.__dict__
    assert "status_code" not in record.__dict__


@pytest.mark.parametrize(
    ("args", "status_code"),
    [
        ((), 200),
        (("client", "GET", "/", "1.1"), 200),
        (("client", "GET", "/", "1.1", 200, "extra"), 200),
        (["client", "GET", "/", "1.1", 200], 200),
        (None, "200"),
        (None, True),
    ],
)
def test_access_formatter_fails_closed_for_invalid_structure(args: object | None, status_code: object) -> None:
    formatter = RedactingAccessFormatter(fmt=ACCESS_FORMAT, use_colors=False)
    record = _access_record(
        target="/unsafe?token=invalid-access-canary",
        status_code=status_code,
        args=args,
    )
    original = record.__dict__.copy()

    rendered = formatter.format(record)

    assert rendered == FORMAT_FAILED
    assert "invalid-access-canary" not in rendered
    assert record.__dict__ == original


def test_generic_formatter_redacts_positional_mapping_exception_stack_and_extras_without_mutation() -> None:
    formatter = RedactingFormatter(
        "%(message)s api_key=%(api_key)s metadata=%(metadata)s",
    )
    try:
        raise RuntimeError("authorization: Bearer exception-canary")
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "newscraft.phase5",
        logging.ERROR,
        "<phase5-test>",
        2,
        "provider failed token=%s safe=%s",
        ("argument-canary", "visible"),
        exc_info,
    )
    record.api_key = "extra-canary"
    record.metadata = {"cookie": "cookie-canary", "safe": "yes"}
    record.stack_info = "stack credential=stack-canary"
    original = record.__dict__.copy()

    rendered = formatter.format(record)

    assert all(
        canary not in rendered
        for canary in (
            "argument-canary",
            "exception-canary",
            "extra-canary",
            "cookie-canary",
            "stack-canary",
        )
    )
    assert "safe=visible" in rendered
    assert "'safe': 'yes'" in rendered
    assert rendered.count("[REDACTED]") >= 5
    assert record.__dict__ == original

    mapping_record = logging.LogRecord(
        "newscraft.phase5",
        logging.INFO,
        "<phase5-test>",
        3,
        "mapping credential=%(credential)s safe=%(safe)s",
        ({"credential": "mapping-canary", "safe": "visible"},),
        None,
    )
    mapping_rendered = RedactingFormatter("%(message)s").format(mapping_record)
    assert "mapping-canary" not in mapping_rendered
    assert "safe=visible" in mapping_rendered


def test_generic_formatter_handles_non_string_and_hostile_values_without_invoking_them() -> None:
    formatter = RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        "newscraft.phase5",
        logging.INFO,
        "<phase5-test>",
        4,
        HostileString(),
        (),
        None,
    )

    rendered = formatter.format(record)

    assert rendered == "[HostileString]"
    assert "hostile-str-canary" not in rendered


def test_generic_formatter_returns_constant_sentinel_for_message_or_delegate_failure() -> None:
    malformed = logging.LogRecord(
        "newscraft.phase5",
        logging.WARNING,
        "<phase5-test>",
        5,
        "password=malformed-canary values=%s %s",
        ("one",),
        None,
    )
    malformed_output = RedactingFormatter("%(message)s").format(malformed)
    delegated_output = RedactingFormatter(delegate=ExplodingFormatter()).format(malformed)

    assert malformed_output == "[LOG_FORMAT_FAILED] logger=newscraft.phase5 level=WARNING"
    assert delegated_output == "[LOG_FORMAT_FAILED] logger=newscraft.phase5 level=WARNING"
    assert "malformed-canary" not in malformed_output + delegated_output
    assert "delegate-canary" not in malformed_output + delegated_output


def test_credential_and_sensitive_query_canaries_are_absent() -> None:
    generic = RedactingFormatter("%(message)s")
    messages = (
        "api_key=api-key-canary",
        "bot token 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        "Authorization: Bearer authorization-canary",
        "Cookie: session=cookie-canary",
        "secret_ref=secret-reference-canary password=secret-value-canary",
        "proxy http://proxy-user:proxy-password@proxy.example:8080/path",
        "telegram_session=telegram-session-canary",
    )
    rendered_messages: list[str] = []
    for index, message in enumerate(messages):
        record = logging.LogRecord(
            "newscraft.phase5",
            logging.INFO,
            "<phase5-test>",
            index,
            message,
            (),
            None,
        )
        rendered_messages.append(generic.format(record))

    access = RedactingAccessFormatter(fmt=ACCESS_FORMAT, use_colors=False)
    rendered_messages.append(
        access.format(
            _access_record(
                target=(
                    "/search?token=query-token-canary&key=query-key-canary"
                    "&session_id=query-session-canary&credential=query-credential-canary&safe=visible"
                )
            )
        )
    )
    combined = "\n".join(rendered_messages)

    assert "safe=visible" in combined
    assert "proxy.example:8080/path" in combined
    assert all(
        canary not in combined
        for canary in (
            "api-key-canary",
            "123456789:",
            "authorization-canary",
            "cookie-canary",
            "secret-reference-canary",
            "secret-value-canary",
            "proxy-user",
            "proxy-password",
            "telegram-session-canary",
            "query-token-canary",
            "query-key-canary",
            "query-session-canary",
            "query-credential-canary",
        )
    )


def test_multiple_handlers_format_independent_clones_and_emit_one_line_each() -> None:
    streams = (io.StringIO(), io.StringIO())
    handlers = [logging.StreamHandler(stream) for stream in streams]
    for handler in handlers:
        handler.setFormatter(RedactingFormatter("%(message)s metadata=%(metadata)s"))
    record = logging.LogRecord(
        "newscraft.phase5",
        logging.INFO,
        "<phase5-test>",
        6,
        "token=multi-handler-canary safe=%s",
        ("visible",),
        None,
    )
    record.metadata = {"authorization": "handler-extra-canary", "safe": "yes"}
    original = record.__dict__.copy()

    for handler in handlers:
        handler.handle(record)

    outputs = [stream.getvalue() for stream in streams]
    assert outputs[0] == outputs[1]
    assert all(output.count("\n") == 1 for output in outputs)
    assert "multi-handler-canary" not in outputs[0]
    assert "handler-extra-canary" not in outputs[0]
    assert record.__dict__ == original


def test_configure_logging_installs_explicit_access_and_generic_formatters_idempotently() -> None:
    with _preserve_logging_state("uvicorn", "uvicorn.error", "uvicorn.access", "newscraft.phase5.config"):
        root = logging.getLogger()
        root_handler = logging.StreamHandler(io.StringIO())
        root_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        root.handlers = [root_handler]

        uvicorn_handler = logging.StreamHandler(io.StringIO())
        uvicorn_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger("uvicorn").handlers = [uvicorn_handler]

        access_handler = logging.StreamHandler(io.StringIO())
        access_handler.setFormatter(AccessFormatter(fmt=ACCESS_FORMAT, use_colors=False))
        logging.getLogger("uvicorn.access").handlers = [access_handler]
        logging.getLogger("uvicorn.access").propagate = False

        configure_logging()
        installed = (root_handler.formatter, uvicorn_handler.formatter, access_handler.formatter)
        configure_logging()

        assert isinstance(root_handler.formatter, RedactingFormatter)
        assert isinstance(uvicorn_handler.formatter, RedactingFormatter)
        assert isinstance(access_handler.formatter, RedactingAccessFormatter)
        assert (root_handler.formatter, uvicorn_handler.formatter, access_handler.formatter) == installed
        assert not any(logger.filters for logger in (root, logging.getLogger("uvicorn.access")))


def test_ten_thousand_generated_valid_and_malformed_records_never_raise_or_leak() -> None:
    generic = RedactingFormatter("%(message)s")
    access = RedactingAccessFormatter(fmt=ACCESS_FORMAT, use_colors=False)

    for index in range(10_000):
        canary = f"phase5-stress-canary-{index}"
        mode = index % 4
        if mode == 0:
            rendered = access.format(_access_record(target=f"/items/{index}?token={canary}&safe={index}"))
        elif mode == 1:
            rendered = access.format(_access_record(args=("client", "GET", f"token={canary}")))
        elif mode == 2:
            record = logging.LogRecord(
                "newscraft.phase5.stress",
                logging.INFO,
                "<phase5-test>",
                index,
                "request token=%s index=%d",
                (canary, index),
                None,
            )
            rendered = generic.format(record)
        else:
            record = logging.LogRecord(
                "newscraft.phase5.stress",
                logging.INFO,
                "<phase5-test>",
                index,
                f"password={canary} broken=%s %s",
                ("one",),
                None,
            )
            rendered = generic.format(record)
        assert "phase5-stress-canary" not in rendered


@pytest.mark.asyncio
async def test_real_uvicorn_server_emits_safe_access_and_error_lines_for_asgi_requests() -> None:
    app = FastAPI()

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("api_key=asgi-exception-canary")

    with _preserve_logging_state("uvicorn", "uvicorn.error", "uvicorn.access"):
        config = Config(
            app,
            host="127.0.0.1",
            port=0,
            lifespan="off",
            log_config=copy.deepcopy(LOGGING_CONFIG),
            use_colors=False,
        )
        access_stream = io.StringIO()
        error_stream = io.StringIO()
        for handler in logging.getLogger("uvicorn.access").handlers:
            handler.stream = access_stream
        for handler in logging.getLogger("uvicorn").handlers:
            handler.stream = error_stream
        configure_logging()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(config.backlog)
        port = sock.getsockname()[1]
        server = Server(config)
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            for _ in range(500):
                if server.started:
                    break
                if server_task.done():
                    await server_task
                await asyncio.sleep(0.01)
            assert server.started

            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                success = await client.get("/ok?token=asgi-200-canary&safe=visible")
                missing = await client.get("/missing?key=asgi-404-canary")
                failed = await client.get("/explode?session_id=asgi-500-canary")
            assert (success.status_code, missing.status_code, failed.status_code) == (200, 404, 500)
        finally:
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=10)
            sock.close()

        access_output = access_stream.getvalue()
        error_output = error_stream.getvalue()
        access_lines = [line for line in access_output.splitlines() if '"GET ' in line]

        assert len(access_lines) == 3
        assert any(
            "GET /ok?token=%5BREDACTED%5D&safe=visible HTTP/1.1" in line and "200 OK" in line for line in access_lines
        )
        assert any(
            "GET /missing?key=%5BREDACTED%5D HTTP/1.1" in line and "404 Not Found" in line for line in access_lines
        )
        assert any(
            "GET /explode?session_id=%5BREDACTED%5D HTTP/1.1" in line and "500 Internal Server Error" in line
            for line in access_lines
        )
        assert all(
            canary not in access_output + error_output
            for canary in (
                "asgi-200-canary",
                "asgi-404-canary",
                "asgi-500-canary",
                "asgi-exception-canary",
            )
        )
        assert "Logging error" not in access_output + error_output
        assert "not enough values to unpack" not in access_output + error_output
