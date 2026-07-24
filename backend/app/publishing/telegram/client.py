from __future__ import annotations

import hashlib
import json
import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx

from app.core.redaction import redact_secrets
from app.publishing.telegram.contracts import TelegramOperationResult, TelegramPublishOperation

_UPLOAD_MIME_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".zip": "application/zip",
    ".bin": "application/octet-stream",
}


class TelegramClientError(RuntimeError):
    def __init__(self, message: str, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.metadata = metadata or {}


class TelegramRateLimited(TelegramClientError):
    def __init__(self, *, retry_after: int, metadata: dict[str, Any] | None = None) -> None:
        super().__init__("Telegram rate limit exceeded", metadata=metadata)
        self.retry_after = retry_after


class TelegramRetryableBeforeDispatch(TelegramClientError):
    """The request could not connect and is safe to retry."""


class TelegramAmbiguousError(TelegramClientError):
    """The request may have reached Telegram and requires reconciliation."""


class TelegramPermanentError(TelegramClientError):
    """Telegram rejected the request permanently."""


def _safe_metadata(value: Any, token: str, *, status: int | None = None) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    metadata: dict[str, Any] = {
        "http_status": status,
        "description": source.get("description"),
        "parameters": source.get("parameters", {}),
    }
    sanitized = redact_secrets(metadata, secrets=(token,))
    return sanitized if isinstance(sanitized, dict) else {}


def _safe_result(value: Any, token: str) -> dict[str, Any]:
    sanitized = redact_secrets(value, secrets=(token,))
    return sanitized if isinstance(sanitized, dict) else {}


def _multipart_data(fields: dict[str, Any]) -> dict[str, str]:
    return {
        key: json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        if isinstance(value, (dict, list))
        else str(value)
        for key, value in fields.items()
    }


def _retry_after(payload: Any) -> int:
    parameters = payload.get("parameters", {}) if isinstance(payload, dict) else {}
    value = parameters.get("retry_after") if isinstance(parameters, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 1


def _bot_server_error(payload: Any) -> bool:
    error_code = payload.get("error_code") if isinstance(payload, dict) else None
    return isinstance(error_code, int) and not isinstance(error_code, bool) and error_code >= 500


class TelegramBotClient:
    def __init__(self, http: httpx.AsyncClient, *, base_url: str = "https://api.telegram.org") -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    async def execute(self, operation: TelegramPublishOperation, token: str) -> TelegramOperationResult:
        _validate_upload_contract(operation)
        url = f"{self._base_url}/bot{token}/{operation.method}"
        try:
            if operation.file_paths:
                response = await self._post_multipart(url, operation)
            else:
                response = await self._http.post(url, json=operation.fields)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            metadata = _safe_metadata({"description": "telegram_connect_failed"}, token)
            raise TelegramRetryableBeforeDispatch(
                "Telegram connection failed before dispatch", metadata=metadata
            ) from None
        except httpx.TransportError:
            metadata = _safe_metadata({"description": "telegram_transport_failed"}, token)
            raise TelegramAmbiguousError("Telegram response timed out after dispatch", metadata=metadata) from None

        payload = self._response_payload(response)
        metadata = _safe_metadata(payload, token, status=response.status_code)
        if response.status_code == 429 or (isinstance(payload, dict) and payload.get("error_code") == 429):
            raise TelegramRateLimited(retry_after=_retry_after(payload), metadata=metadata)
        if response.status_code >= 500 or _bot_server_error(payload):
            raise TelegramAmbiguousError("Telegram server failed after dispatch", metadata=metadata)
        if response.status_code >= 400:
            raise TelegramPermanentError("Telegram rejected the publish operation", metadata=metadata)
        if not isinstance(payload, dict):
            raise TelegramAmbiguousError("Telegram returned an invalid response", metadata=metadata)
        if payload.get("ok") is not True:
            raise TelegramPermanentError("Telegram rejected the publish operation", metadata=metadata)

        try:
            result = payload.get("result")
            if operation.method == "sendMediaGroup" and not isinstance(result, list):
                raise TypeError("media group result must be a list")
            if operation.method != "sendMediaGroup" and not isinstance(result, dict):
                raise TypeError("single operation result must be an object")
            remote_ids = _remote_message_ids(result)
            expected_count = len(operation.file_paths) if operation.method == "sendMediaGroup" else 1
            if len(remote_ids) != expected_count:
                raise ValueError("unexpected result count")
        except (TypeError, ValueError):
            raise TelegramAmbiguousError("Telegram returned an invalid success response", metadata=metadata) from None
        success_metadata = {
            "http_status": response.status_code,
            "ok": True,
            "method": operation.method,
            "result_count": len(remote_ids),
        }
        return TelegramOperationResult(remote_ids, success_metadata)

    async def get_me(self, token: str) -> dict[str, Any]:
        result = await self._check_method("getMe", token, {})
        bot_id = result.get("id")
        username = result.get("username")
        if (
            not isinstance(bot_id, int)
            or isinstance(bot_id, bool)
            or bot_id <= 0
            or not isinstance(username, str)
            or not username
            or result.get("is_bot") is not True
        ):
            raise TelegramAmbiguousError("Telegram returned an invalid bot identity")
        return _safe_result({"id": bot_id, "username": username}, token)

    async def get_chat_member(self, target_ref: str, user_id: int, token: str) -> dict[str, Any]:
        result = await self._check_method(
            "getChatMember",
            token,
            {"chat_id": target_ref, "user_id": user_id},
        )
        status = result.get("status")
        if status not in {"creator", "administrator", "member", "restricted", "left", "kicked"}:
            raise TelegramAmbiguousError("Telegram returned an invalid administrator response")
        return {"status": status, "administrator": status in {"creator", "administrator"}}

    async def get_chat(self, target_ref: str, token: str) -> dict[str, Any]:
        """Resolve destination health without exposing the Bot API token."""

        url = f"{self._base_url}/bot{token}/getChat"
        try:
            response = await self._http.post(url, json={"chat_id": target_ref})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            metadata = _safe_metadata({"description": "telegram_connect_failed"}, token)
            raise TelegramRetryableBeforeDispatch(
                "Telegram connection failed before dispatch", metadata=metadata
            ) from None
        except httpx.TransportError:
            metadata = _safe_metadata({"description": "telegram_transport_failed"}, token)
            raise TelegramAmbiguousError("Telegram response failed after dispatch", metadata=metadata) from None
        payload = self._response_payload(response)
        metadata = _safe_metadata(payload, token, status=response.status_code)
        if response.status_code == 429 or (isinstance(payload, dict) and payload.get("error_code") == 429):
            raise TelegramRateLimited(retry_after=_retry_after(payload), metadata=metadata)
        if response.status_code >= 500 or _bot_server_error(payload) or not isinstance(payload, dict):
            raise TelegramAmbiguousError("Telegram returned an invalid destination response", metadata=metadata)
        if response.status_code >= 400 or payload.get("ok") is not True:
            raise TelegramPermanentError("Telegram rejected the destination check", metadata=metadata)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegramAmbiguousError("Telegram returned an invalid destination response", metadata=metadata)
        chat_id = result.get("id")
        chat_type = result.get("type")
        if (
            not isinstance(chat_id, int)
            or isinstance(chat_id, bool)
            or chat_id == 0
            or chat_type not in {"private", "group", "supergroup", "channel"}
        ):
            raise TelegramAmbiguousError("Telegram returned an invalid destination identity", metadata=metadata)
        return _safe_result(
            {key: result[key] for key in ("id", "type", "username", "title") if key in result},
            token,
        )

    async def _check_method(self, method: str, token: str, fields: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/bot{token}/{method}"
        try:
            response = await self._http.post(url, json=fields)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            metadata = _safe_metadata({"description": "telegram_connect_failed"}, token)
            raise TelegramRetryableBeforeDispatch(
                "Telegram connection failed before dispatch", metadata=metadata
            ) from None
        except httpx.TransportError:
            metadata = _safe_metadata({"description": "telegram_transport_failed"}, token)
            raise TelegramAmbiguousError("Telegram response failed after dispatch", metadata=metadata) from None
        payload = self._response_payload(response)
        metadata = _safe_metadata(payload, token, status=response.status_code)
        if response.status_code == 429 or (isinstance(payload, dict) and payload.get("error_code") == 429):
            raise TelegramRateLimited(retry_after=_retry_after(payload), metadata=metadata)
        if response.status_code >= 500 or _bot_server_error(payload) or not isinstance(payload, dict):
            raise TelegramAmbiguousError("Telegram returned an invalid health response", metadata=metadata)
        if response.status_code >= 400 or payload.get("ok") is not True:
            raise TelegramPermanentError("Telegram rejected the health check", metadata=metadata)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegramAmbiguousError("Telegram returned an invalid health response", metadata=metadata)
        return result

    async def _post_multipart(self, url: str, operation: TelegramPublishOperation) -> httpx.Response:
        with ExitStack() as stack:
            files: dict[str, tuple[str, Any, str]] = {}
            try:
                for upload, path in zip(operation.uploads, operation.file_paths, strict=True):
                    source = stack.enter_context(Path(path).open("rb"))
                    digest = hashlib.sha256()
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                    if digest.hexdigest() != upload.checksum_sha256:
                        raise TelegramPermanentError("Telegram upload no longer matches its publish plan")
                    source.seek(0)
                    files[upload.attach_name] = (upload.filename, source, upload.mime_type)
            except OSError:
                raise TelegramPermanentError("Telegram upload is not readable") from None
            return await self._http.post(url, data=_multipart_data(operation.fields), files=files)

    @staticmethod
    def _response_payload(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None


def _remote_message_ids(result: Any) -> tuple[int, ...]:
    values = result if isinstance(result, list) else [result]
    if not values:
        raise ValueError("empty result")
    remote_ids: list[int] = []
    for item in values:
        if not isinstance(item, dict):
            raise TypeError("result item must be an object")
        message_id = item.get("message_id")
        if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
            raise TypeError("message_id must be an integer")
        remote_ids.append(message_id)
    return tuple(remote_ids)


def _validate_upload_contract(operation: TelegramPublishOperation) -> None:
    if not operation.file_paths and not operation.uploads:
        return
    if not operation.file_paths or len(operation.uploads) != len(operation.file_paths):
        raise TelegramPermanentError("Telegram upload plan is invalid")
    raw_group_items = operation.fields.get("media", []) if operation.method == "sendMediaGroup" else []
    group_items = raw_group_items if isinstance(raw_group_items, list) else []
    for index, upload in enumerate(operation.uploads):
        if operation.method == "sendMediaGroup":
            expected_media_type = group_items[index].get("type") if index < len(group_items) else None
        else:
            expected_media_type = {
                "sendPhoto": "photo",
                "sendVideo": "video",
                "sendDocument": "document",
            }.get(operation.method)
        suffix = Path(upload.filename).suffix.casefold()
        if (
            upload.attach_name != f"file{index}"
            or upload.filename != f"upload-{index}{suffix}"
            or not re.fullmatch(r"[0-9a-f]{64}", upload.checksum_sha256)
            or _UPLOAD_MIME_BY_EXTENSION.get(suffix) != upload.mime_type
            or upload.media_type != expected_media_type
        ):
            raise TelegramPermanentError("Telegram upload plan is invalid")
