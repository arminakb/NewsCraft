from app.generation.default_prompts import (
    DEFAULT_TELEGRAM_SYSTEM_TEMPLATE,
    DEFAULT_TELEGRAM_USER_TEMPLATE,
    seed_default_editorial_prompts,
    seed_default_telegram_configuration,
    seed_default_telegram_prompt,
    telegram_prompt_checksum,
)
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplate, PromptTemplateVersion


class FakeScalars:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)


class FakeSession:
    def __init__(self):
        self.rows = []

    async def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return FakeScalars([row for row in self.rows if isinstance(row, entity)])

    def add(self, value):
        self.rows.append(value)

    async def flush(self):
        return None


async def test_default_prompt_seed_is_idempotent_and_versions_content(monkeypatch):
    session = FakeSession()
    first = await seed_default_telegram_prompt(session)
    second = await seed_default_telegram_prompt(session)

    assert first.id == second.id
    assert first.version == 1
    assert first.is_active is True
    assert first.output_schema_version == "telegram_rewrite.v1"
    assert first.checksum_sha256 == telegram_prompt_checksum(
        first.system_template, first.user_template, first.output_schema
    )
    assert all(
        f"{{{name}}}" in first.user_template
        for name in (
            "source_text",
            "source_url",
            "source_channel",
            "language",
            "direction",
            "attribution_policy",
            "custom_footer",
        )
    )
    assert "do not invent facts" in first.system_template.casefold()
    assert "data" in first.system_template.casefold()

    monkeypatch.setattr(
        "app.generation.default_prompts.DEFAULT_TELEGRAM_SYSTEM_TEMPLATE",
        DEFAULT_TELEGRAM_SYSTEM_TEMPLATE + "\nUse short paragraphs.",
    )
    changed = await seed_default_telegram_prompt(session)
    assert changed.version == 2
    assert changed.id != first.id
    assert first.system_template == DEFAULT_TELEGRAM_SYSTEM_TEMPLATE
    assert first.user_template == DEFAULT_TELEGRAM_USER_TEMPLATE

    monkeypatch.setattr(
        "app.generation.default_prompts.DEFAULT_TELEGRAM_SYSTEM_TEMPLATE",
        DEFAULT_TELEGRAM_SYSTEM_TEMPLATE,
    )
    progressed = await seed_default_telegram_prompt(session)
    assert progressed.id == changed.id
    assert progressed.version == 2
    assert changed.is_active is True
    assert first.is_active is False


async def test_default_brand_and_provider_profiles_make_a_clean_install_usable():
    session = FakeSession()
    result = await seed_default_telegram_configuration(session, openrouter_available=True)
    replay = await seed_default_telegram_configuration(session, openrouter_available=True)

    assert result.brand.name == "Default Newsroom"
    assert result.brand.output_language == "fa"
    assert {profile.provider_type for profile in result.providers} == {"fake", "openrouter"}
    assert result.provider("fake").enabled is True
    assert result.provider("openrouter").secret_ref == "OPENROUTER_API_KEY"
    assert result.provider("openrouter").enabled is True
    assert replay.brand.id == result.brand.id
    assert len([row for row in session.rows if isinstance(row, BrandProfile)]) == 1
    assert len([row for row in session.rows if isinstance(row, AIProviderProfile)]) == 2
    assert len([row for row in session.rows if isinstance(row, PromptTemplate)]) == 0
    assert len([row for row in session.rows if isinstance(row, PromptTemplateVersion)]) == 0

    unavailable = await seed_default_telegram_configuration(session, openrouter_available=False)
    assert unavailable.provider("openrouter").enabled is False
    available_again = await seed_default_telegram_configuration(session, openrouter_available=True)
    assert available_again.provider("openrouter").enabled is True


async def test_editorial_prompt_seed_is_idempotent_and_keeps_two_active_purposes():
    session = FakeSession()
    first = await seed_default_editorial_prompts(session)
    second = await seed_default_editorial_prompts(session)
    assert first.canonical_story.id == second.canonical_story.id
    assert first.telegram_pack.id == second.telegram_pack.id
    assert first.canonical_story.prompt_template.purpose_key == "canonical_story"
    assert first.telegram_pack.prompt_template.purpose_key == "telegram_pack"
    assert first.canonical_story.is_active is True
    assert first.telegram_pack.is_active is True


async def test_editorial_seed_never_reactivates_an_old_default_over_custom_active():
    session = FakeSession()
    first = await seed_default_editorial_prompts(session)
    first.canonical_story.is_active = False
    custom = PromptTemplateVersion(
        id=__import__("uuid").uuid4(),
        prompt_template_id=first.canonical_story.prompt_template_id,
        version=2,
        system_template="Custom system",
        user_template="Story {story_title}; evidence {evidence_json}",
        output_schema_version=first.canonical_story.output_schema_version,
        output_schema=first.canonical_story.output_schema,
        checksum_sha256="f" * 64,
        is_active=True,
    )
    session.add(custom)
    repaired = await seed_default_editorial_prompts(session)
    replay = await seed_default_editorial_prompts(session)
    assert repaired.canonical_story.version == 3
    assert repaired.canonical_story.id == replay.canonical_story.id
    assert repaired.canonical_story.is_active is True
    assert custom.is_active is False


async def test_application_lifespan_seeds_defaults_in_one_transaction(monkeypatch):
    import app.main as main

    calls = []

    class SessionContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            calls.append("exit")

        async def commit(self):
            calls.append("commit")

    session = SessionContext()

    async def seed_prompt(value):
        assert value is session
        calls.append("prompt")

    async def seed_configuration(value):
        assert value is session
        calls.append("configuration")

    async def seed_editorial(value):
        assert value is session
        calls.append("editorial")

    async def seed_codex(value, *, enabled, model):
        assert value is session
        assert enabled is main.settings.codex_enabled
        assert model == "gpt-5.4"
        calls.append("codex")

    async def seed_provider_compatibility(value):
        assert value is session
        calls.append("provider_compatibility")

    monkeypatch.setattr(main, "async_session", lambda: session)
    monkeypatch.setattr(main, "seed_default_telegram_prompt", seed_prompt)
    monkeypatch.setattr(main, "seed_default_telegram_configuration", seed_configuration)
    monkeypatch.setattr(main, "seed_default_editorial_prompts", seed_editorial)
    monkeypatch.setattr(main, "seed_codex_provider_profile", seed_codex)
    monkeypatch.setattr(main, "seed_legacy_provider_compatibility", seed_provider_compatibility)

    async with main.lifespan(main.app):
        calls.append("serve")

    assert calls == [
        "prompt",
        "editorial",
        "configuration",
        "codex",
        "provider_compatibility",
        "commit",
        "exit",
        "serve",
    ]
