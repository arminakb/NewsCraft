from app.db.model_registry import Base

PLATFORM_SPINE_COLUMNS = {
    "stories": {
        "id",
        "title",
        "status",
        "primary_language",
        "superseded_by_id",
        "created_at",
        "updated_at",
    },
    "story_evidence_snapshots": {
        "id",
        "story_id",
        "content_item_id",
        "evidence_key",
        "source_url",
        "title",
        "content_text",
        "authors",
        "published_at",
        "content_sha256",
        "snapshot_metadata",
        "captured_at",
    },
    "story_revisions": {
        "id",
        "story_id",
        "parent_revision_id",
        "revision_number",
        "narrative",
        "facts",
        "disagreements",
        "angles",
        "citations",
        "created_by",
        "created_at",
    },
    "story_evidence_links": {
        "id",
        "story_revision_id",
        "evidence_snapshot_id",
        "claim_key",
        "relationship",
        "created_at",
    },
    "brand_profiles": {
        "id",
        "name",
        "output_language",
        "tone",
        "editorial_rules",
        "attribution_rules",
        "default_hashtags",
        "platform_preferences",
        "is_default",
        "created_at",
        "updated_at",
    },
    "prompt_templates": {
        "id",
        "purpose_key",
        "name",
        "description",
        "created_at",
        "updated_at",
    },
    "prompt_template_versions": {
        "id",
        "prompt_template_id",
        "version",
        "system_template",
        "user_template",
        "output_schema_version",
        "output_schema",
        "checksum_sha256",
        "is_active",
        "created_at",
    },
    "ai_provider_profiles": {
        "id",
        "name",
        "provider_type",
        "default_model",
        "secret_ref",
        "settings",
        "enabled",
        "created_at",
        "updated_at",
    },
    "research_runs": {
        "id",
        "story_id",
        "requested_mode",
        "provider_profile_id",
        "status",
        "query_budget",
        "page_budget",
        "time_budget_seconds",
        "result_story_revision_id",
        "created_at",
        "started_at",
        "finished_at",
    },
    "research_attempts": {
        "id",
        "research_run_id",
        "attempt_number",
        "queries",
        "status",
        "usage",
        "error_class",
        "error_code",
        "error_message",
        "started_at",
        "finished_at",
    },
    "research_sources": {
        "id",
        "research_run_id",
        "url",
        "title",
        "publisher",
        "published_at",
        "content_sha256",
        "extraction_status",
        "relevance",
        "citation_key",
        "snapshot_metadata",
        "created_at",
    },
    "generation_runs": {
        "id",
        "story_revision_id",
        "provider_profile_id",
        "prompt_template_version_id",
        "requested_model",
        "status",
        "input_hash",
        "request_payload",
        "output_payload",
        "error_class",
        "error_code",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
    },
    "generation_attempts": {
        "id",
        "generation_run_id",
        "attempt_number",
        "provider",
        "requested_model",
        "resolved_model",
        "prompt_snapshot",
        "response_payload",
        "usage",
        "validation_errors",
        "status",
        "error_class",
        "error_code",
        "error_message",
        "started_at",
        "finished_at",
    },
    "content_packs": {
        "id",
        "story_revision_id",
        "brand_profile_id",
        "status",
        "created_at",
        "updated_at",
    },
    "platform_variants": {
        "id",
        "content_pack_id",
        "platform",
        "created_at",
    },
    "platform_variant_revisions": {
        "id",
        "platform_variant_id",
        "parent_revision_id",
        "generation_attempt_id",
        "revision_number",
        "content",
        "content_hash",
        "evidence_map",
        "validation_results",
        "approval_state",
        "approval_note",
        "approved_at",
        "created_by",
        "created_at",
    },
    "destinations": {
        "id",
        "name",
        "platform",
        "target_ref",
        "secret_ref",
        "enabled",
        "health_status",
        "last_health_check_at",
        "settings",
        "created_at",
        "updated_at",
    },
    "automation_routes": {
        "id",
        "name",
        "source_id",
        "destination_id",
        "brand_profile_id",
        "prompt_template_version_id",
        "ai_provider_profile_id",
        "access_mode",
        "research_mode",
        "content_filters",
        "media_policy",
        "attribution_policy",
        "custom_footer",
        "publishing_policy",
        "poll_interval_seconds",
        "quiet_hours",
        "retry_policy",
        "cursor_state",
        "enabled",
        "paused_at",
        "last_polled_at",
        "next_poll_at",
        "backfill_limit",
        "backfill_since",
        "created_at",
        "updated_at",
    },
    "publish_jobs": {
        "id",
        "workflow_job_id",
        "destination_id",
        "platform_variant_revision_id",
        "status",
        "idempotency_key",
        "payload_hash",
        "scheduled_for",
        "created_at",
        "updated_at",
    },
    "publish_attempts": {
        "id",
        "publish_job_id",
        "attempt_number",
        "sanitized_payload",
        "payload_hash",
        "status",
        "http_status",
        "remote_response",
        "error_class",
        "error_code",
        "error_message",
        "started_at",
        "finished_at",
    },
    "publications": {
        "id",
        "publish_job_id",
        "destination_id",
        "platform_variant_revision_id",
        "remote_message_ids",
        "permalink",
        "payload_hash",
        "published_at",
        "reconciliation_status",
    },
}

PLATFORM_SPINE_UNIQUE_CONSTRAINTS = {
    "story_evidence_snapshots": {"uq_story_evidence_key"},
    "story_revisions": {"uq_story_revision_number"},
    "story_evidence_links": {"uq_story_evidence_link_claim"},
    "brand_profiles": {"uq_brand_profiles_name"},
    "prompt_templates": {"uq_prompt_templates_purpose_key"},
    "prompt_template_versions": {"uq_prompt_template_version"},
    "ai_provider_profiles": {"uq_ai_provider_profiles_name"},
    "research_attempts": {"uq_research_attempt_number"},
    "research_sources": {"uq_research_source_url"},
    "generation_attempts": {"uq_generation_attempt_number"},
    "content_packs": {"uq_content_pack_story_brand"},
    "platform_variants": {"uq_platform_variant_platform"},
    "platform_variant_revisions": {"uq_platform_variant_revision_number"},
    "destinations": {"uq_destination_platform_target"},
    "publish_jobs": {"uq_publish_jobs_idempotency_key"},
    "publish_attempts": {"uq_publish_attempt_number"},
    "publications": {
        "uq_publications_publish_job_id",
        "uq_publication_destination_variant_revision",
    },
}


def test_ingestion_tables_are_registered():
    expected = {
        "sources",
        "ingest_runs",
        "raw_payloads",
        "source_items",
        "content_items",
        "item_identities",
        "media_assets",
        "item_media",
        "content_drafts",
    }

    assert expected.issubset(set(Base.metadata.tables))


def test_content_drafts_indexes_content_item_id():
    indexes = {index.name for index in Base.metadata.tables["content_drafts"].indexes}

    assert "ix_content_drafts_content_item" in indexes


def test_content_intelligence_schema_fields_are_registered():
    content_columns = set(Base.metadata.tables["content_items"].columns.keys())
    media_columns = set(Base.metadata.tables["media_assets"].columns.keys())
    source_columns = set(Base.metadata.tables["sources"].columns.keys())

    assert {
        "content_type",
        "content_type_confidence",
        "classification_reasons",
        "classification_metadata",
        "rewrite_bucket",
        "freshness_bucket",
        "source_tier",
        "quality_status",
        "is_rewrite_ready",
        "rewrite_ready_reason",
        "rewrite_blockers",
        "score_breakdown",
        "ranking_metadata",
        "title_quality",
        "title_was_generated",
        "content_intent",
    }.issubset(content_columns)
    assert {
        "media_quality",
        "media_confidence",
        "is_primary_candidate",
        "is_primary",
        "media_source_type",
        "asset_role",
    }.issubset(media_columns)
    assert {
        "last_success_at",
        "last_failure_at",
        "failure_count",
        "last_http_status",
        "last_error_type",
        "last_error_message",
        "last_parse_count",
        "last_suitable_count",
        "last_media_count",
        "health_status",
        "disabled_reason",
    }.issubset(source_columns)


def test_rewrite_candidates_table_is_registered():
    table = Base.metadata.tables["rewrite_candidates"]

    assert {
        "content_item_id",
        "bucket_type",
        "priority_score",
        "status",
        "reason",
        "created_at",
        "updated_at",
    }.issubset(set(table.columns.keys()))
    assert "uq_rewrite_candidates_content_bucket" in {constraint.name for constraint in table.constraints}


def test_platform_spine_tables_columns_and_named_constraints_are_registered():
    for table_name, expected_columns in PLATFORM_SPINE_COLUMNS.items():
        assert table_name in Base.metadata.tables
        assert expected_columns == set(Base.metadata.tables[table_name].columns.keys())

    for table_name, expected_names in PLATFORM_SPINE_UNIQUE_CONSTRAINTS.items():
        constraint_names = {constraint.name for constraint in Base.metadata.tables[table_name].constraints}
        assert expected_names.issubset(constraint_names)


def test_platform_spine_keeps_editorial_and_machine_state_separate():
    content_columns = set(Base.metadata.tables["content_items"].columns.keys())
    revision_columns = set(Base.metadata.tables["platform_variant_revisions"].columns.keys())

    assert "approval_state" not in content_columns
    assert {"approval_state", "content_hash", "revision_number"}.issubset(revision_columns)


def test_platform_revision_approval_states_are_locked():
    revision = Base.metadata.tables["platform_variant_revisions"]
    names = {constraint.name for constraint in revision.constraints}

    assert revision.c.approval_state.server_default.arg == "draft"
    assert "ck_platform_variant_revision_approval_state" in names


def test_destination_stores_a_secret_reference_not_a_secret_value():
    columns = set(Base.metadata.tables["destinations"].columns.keys())

    assert "secret_ref" in columns
    assert "token" not in columns
    assert "api_key" not in columns


def test_evidence_supports_operator_text_and_deterministic_identity():
    table = Base.metadata.tables["story_evidence_snapshots"]
    names = {constraint.name for constraint in table.constraints}

    assert table.c.evidence_key.nullable is False
    assert table.c.source_url.nullable is True
    assert "uq_story_evidence_key" in names


def test_story_canonicalization_pointer_and_active_lookup_are_explicit():
    table = Base.metadata.tables["stories"]
    targets = {foreign_key.target_fullname for foreign_key in table.c.superseded_by_id.foreign_keys}

    assert table.c.superseded_by_id.nullable is True
    assert targets == {"stories.id"}
    assert "ix_stories_active_updated" in {index.name for index in table.indexes}
    active_index = next(index for index in table.indexes if index.name == "ix_stories_active_updated")
    assert active_index.dialect_options["postgresql"]["where"] is not None
