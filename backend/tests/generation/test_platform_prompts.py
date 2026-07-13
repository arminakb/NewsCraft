from app.generation.default_prompts import manual_generation_provider_schema, seed_default_editorial_prompts
from app.generation.editorial_service import EditorialService
from app.generation.models import PromptTemplate, PromptTemplateVersion
from app.generation.platform_schemas import BlogVariantPayload, InstagramVariantPayload, XVariantPayload


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


async def test_platform_prompt_seed_is_idempotent_and_has_one_active_version_per_purpose():
    session = FakeSession()
    first = await seed_default_editorial_prompts(session)
    second = await seed_default_editorial_prompts(session)

    assert first.instagram_pack.id == second.instagram_pack.id
    assert first.x_pack.id == second.x_pack.id
    assert first.blog_pack.id == second.blog_pack.id
    purposes = {row.purpose_key for row in session.rows if isinstance(row, PromptTemplate)}
    assert {"canonical_story", "telegram_pack", "instagram_pack", "x_pack", "blog_pack"} <= purposes
    templates = {row.id: row for row in session.rows if isinstance(row, PromptTemplate)}
    active_purposes = [
        templates[row.prompt_template_id].purpose_key
        for row in session.rows
        if isinstance(row, PromptTemplateVersion) and row.is_active
    ]
    assert active_purposes.count("instagram_pack") == 1
    assert active_purposes.count("x_pack") == 1
    assert active_purposes.count("blog_pack") == 1


async def test_manual_prompt_snapshot_uses_structurally_strict_provider_schema_with_operational_limits_deferred():
    from jsonschema import Draft202012Validator, FormatChecker

    session = FakeSession()
    prompts = await seed_default_editorial_prompts(session)
    schema = manual_generation_provider_schema(InstagramVariantPayload)
    citation = {
        "evidence_key": "evidence:one",
        "evidence_snapshot_id": str(__import__("uuid").uuid4()),
        "source_url": "https://example.com/report",
        "locator": "chars:0-8",
        "excerpt_sha256": "a" * 64,
    }
    output = {
        "hook": "x" * 181,
        "caption": "Grounded",
        "cta": "Read",
        "hashtags": [],
        "alt_text": "Grounded",
        "carousel": [],
        "citations": [citation],
        "manual_checklist": ["Verify"],
    }

    assert prompts.instagram_pack.output_schema == schema
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(output)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(InstagramVariantPayload.model_json_schema()["required"])
    assert "maxLength" not in schema["properties"]["hook"]
    assert "pattern" in manual_generation_provider_schema(BlogVariantPayload)["properties"]["slug"]


def test_every_manual_provider_schema_defers_only_non_integrity_limit_keywords():
    limit_keywords = {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"}

    def remaining_limits(node, path=()):
        found = []
        if isinstance(node, dict):
            found.extend((path, key, node[key]) for key in limit_keywords if key in node)
            for key, value in node.items():
                found.extend(remaining_limits(value, (*path, key)))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                found.extend(remaining_limits(value, (*path, index)))
        return found

    for payload_type in (InstagramVariantPayload, XVariantPayload, BlogVariantPayload):
        schema = manual_generation_provider_schema(payload_type)
        remaining = remaining_limits(schema)
        assert remaining
        for path, _keyword, _value in remaining:
            rendered = "/".join(str(part) for part in path)
            node = schema
            for part in path:
                node = node[part]
            assert "CitationRef" in rendered or node.get("format") == "uri" or node.get("title") == "Citations"


async def test_prompt_resolution_selects_explicit_active_version_not_inactive_highest_number():
    active = PromptTemplateVersion(
        id=__import__("uuid").uuid4(),
        prompt_template_id=__import__("uuid").uuid4(),
        version=2,
        system_template="active",
        user_template="active",
        output_schema_version="instagram_pack.v1",
        output_schema={},
        checksum_sha256="a" * 64,
        is_active=True,
    )
    inactive_higher = PromptTemplateVersion(
        id=__import__("uuid").uuid4(),
        prompt_template_id=active.prompt_template_id,
        version=99,
        system_template="inactive",
        user_template="inactive",
        output_schema_version="instagram_pack.v99",
        output_schema={},
        checksum_sha256="b" * 64,
        is_active=False,
    )

    class Session:
        async def scalars(self, statement):
            return [active]

    selected = await EditorialService(Session()).require_active_prompt_version("instagram_pack")

    assert selected.id == active.id
    assert selected.id != inactive_higher.id
