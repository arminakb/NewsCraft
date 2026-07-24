from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.generation_schemas import PromptActivationCreate
from app.api.generation_settings import activate_prompt_version
from app.generation.default_prompts import (
    prompt_checksum,
    seed_default_telegram_prompt,
)
from app.generation.models import PromptTemplateVersion
from app.security.auth import TEST_ADMIN


async def test_prompt_activation_is_serialized_and_restart_preserves_operator_choice(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        default = await seed_default_telegram_prompt(session)
        custom = PromptTemplateVersion(
            prompt_template_id=default.prompt_template_id,
            version=2,
            system_template="Operator system",
            user_template=default.user_template,
            output_schema_version=default.output_schema_version,
            output_schema=default.output_schema,
            checksum_sha256=prompt_checksum(
                "Operator system",
                default.user_template,
                default.output_schema,
            ),
            is_active=False,
        )
        session.add(custom)
        await session.commit()
        default_id = default.id
        custom_id = custom.id
        template_id = custom.prompt_template_id

    async def activate(version_id, reason):
        async with session_factory() as session:
            return await activate_prompt_version(
                version_id,
                PromptActivationCreate(reason=reason),
                TEST_ADMIN,
                session,
            )

    await asyncio.gather(
        activate(default_id, "Concurrent default selection"),
        activate(custom_id, "Concurrent operator selection"),
    )

    async with session_factory() as session:
        active = list(
            await session.scalars(
                select(PromptTemplateVersion).where(
                    PromptTemplateVersion.prompt_template_id == template_id,
                    PromptTemplateVersion.is_active.is_(True),
                )
            )
        )
        assert len(active) == 1
        chosen_id = active[0].id
        assert active[0].activation_reason in {
            "Concurrent default selection",
            "Concurrent operator selection",
        }
        assert await session.scalar(
            select(func.count())
            .select_from(PromptTemplateVersion)
            .where(PromptTemplateVersion.is_active.is_(True))
        ) == 1

    async with session_factory() as session:
        restarted = await seed_default_telegram_prompt(session)
        await session.commit()
        assert restarted.id == chosen_id
