from __future__ import annotations

from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

_ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "code",
    "em",
    "i",
    "pre",
    "s",
    "strong",
    "u",
}


class _TelegramHTMLValidator(HTMLParser):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _ALLOWED_TAGS:
            raise ValueError(f"unsupported Telegram HTML tag: {tag}")
        if tag != "a" and attrs:
            raise ValueError(f"Telegram HTML tag {tag} cannot have attributes")
        if tag == "a":
            if len(attrs) != 1 or attrs[0][0] != "href" or not attrs[0][1]:
                raise ValueError("Telegram HTML links require exactly one href")
            parsed = urlsplit(attrs[0][1])
            try:
                invalid_port = parsed.port is None and ":" in parsed.netloc.split("@")[-1]
            except ValueError:
                invalid_port = True
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or invalid_port
            ):
                raise ValueError("Telegram HTML links require a safe HTTP URL")
        self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raise ValueError("Telegram HTML formatting tags cannot be self-closing")

    def handle_endtag(self, tag: str) -> None:
        if tag not in _ALLOWED_TAGS:
            raise ValueError(f"unsupported Telegram HTML tag: {tag}")
        if not self._stack or self._stack.pop() != tag:
            raise ValueError("Telegram HTML tags must be properly nested")

    def handle_comment(self, data: str) -> None:
        raise ValueError("Telegram HTML comments are not supported")

    def handle_decl(self, decl: str) -> None:
        raise ValueError("Telegram HTML declarations are not supported")

    def handle_pi(self, data: str) -> None:
        raise ValueError("Telegram HTML processing instructions are not supported")

    def unknown_decl(self, data: str) -> None:
        raise ValueError("Telegram HTML declarations are not supported")

    def close(self) -> None:
        super().close()
        if self._stack:
            raise ValueError("Telegram HTML tags must be closed")


def _validated_html(value: str) -> str:
    validator = _TelegramHTMLValidator(convert_charrefs=False)
    validator.feed(value)
    validator.close()
    return value


class TelegramRewriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_text: str = Field(min_length=1)
    source_url: str | None
    source_channel: str
    language: str
    direction: Literal["ltr", "rtl"]
    attribution_policy: Literal["preserve", "remove", "custom"]
    custom_footer: str | None


class TelegramButton(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=64)
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def reject_url_userinfo(cls, value: HttpUrl) -> HttpUrl:
        if value.username is not None or value.password is not None:
            raise ValueError("Telegram button URLs cannot contain userinfo")
        return value


class TelegramRewriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4096)
    parse_mode: Literal["HTML"] = "HTML"
    buttons: list[TelegramButton] = Field(default_factory=list, max_length=8)

    _validate_body = field_validator("body")(_validated_html)


class TelegramVariantContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4096)
    parse_mode: Literal["HTML"] = "HTML"
    buttons: list[TelegramButton] = Field(default_factory=list, max_length=8)
    source_item_id: UUID | None
    source_url: HttpUrl | None
    media_policy: Literal["preserve", "omit", "replace_manually"]
    media_asset_ids: list[UUID]
    direction: Literal["ltr", "rtl"]
    dry_run: bool

    _validate_body = field_validator("body")(_validated_html)


class TelegramEvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_snapshot_id: UUID
    evidence_key: str = Field(min_length=1)
    source_url: HttpUrl | None
    locator: str = Field(pattern=r"^chars:\d+-\d+$")
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
