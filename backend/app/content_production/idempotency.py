from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import IntegrityError


def artifact_id(command_id: uuid.UUID, artifact_type: str, discriminator: str = "") -> uuid.UUID:
    return uuid.uuid5(command_id, f"{artifact_type}:{discriminator}")


async def create_or_get_artifact[ArtifactT](
    session,
    model: type[ArtifactT],
    object_id: uuid.UUID,
    create: Callable[[], Awaitable[ArtifactT]],
) -> ArtifactT:
    existing = await _get_by_id(session, model, object_id)
    if existing is not None:
        return existing

    begin_nested = getattr(session, "begin_nested", None)
    if begin_nested is None:
        return await create()

    try:
        async with begin_nested():
            return await create()
    except IntegrityError as exc:
        if _constraint_name(exc) != f"{model.__tablename__}_pkey":
            raise
        existing = await _get_by_id(session, model, object_id)
        if existing is None:
            raise
        return existing


def _constraint_name(exc: IntegrityError) -> str | None:
    current = exc.orig
    while current is not None:
        value = getattr(current, "constraint_name", None)
        if value:
            return str(value)
        current = getattr(current, "__cause__", None)
    return None


async def _get_by_id[ArtifactT](session, model: type[ArtifactT], object_id: uuid.UUID) -> ArtifactT | None:
    get = getattr(session, "get", None)
    if get is not None:
        return await get(model, object_id)
    return next(
        (
            row
            for row in getattr(session, "added", [])
            if isinstance(row, model) and getattr(row, "id", None) == object_id
        ),
        None,
    )
