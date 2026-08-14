"""deduplicate weak item identities and media assets, then enforce uniqueness

Revision ID: 0028_wave2a_ingest
Revises: 0035_feed_clear
"""

from alembic import op

revision = "0036_wave2a_ingest"
down_revision = "0035_feed_clear"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Weak, source-scoped identities were written with a plain INSERT and sit
    # outside every unique index, so each ingest cycle appended a fresh row.
    # Collapse the accumulated duplicates onto the newest row per identity.
    op.execute(
        """
        DELETE FROM item_identities AS victim
        USING (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY source_id, identity_type, identity_hash
                    ORDER BY created_at DESC, id DESC
                ) AS rank
            FROM item_identities
            WHERE scope = 'source' AND NOT is_strong AND source_id IS NOT NULL
        ) AS ranked
        WHERE victim.id = ranked.id AND ranked.rank > 1
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_identity_source_weak
        ON item_identities (source_id, identity_type, identity_hash)
        WHERE scope = 'source' AND NOT is_strong
        """
    )

    # media_assets.url_hash had no index at all: lookups were sequential scans
    # and concurrent ingest sessions could insert the same asset twice. Fold
    # live duplicates onto one keeper (preferring a downloaded copy) and move
    # every reference before enforcing uniqueness.
    op.execute(
        """
        CREATE TEMPORARY TABLE media_asset_dedupe ON COMMIT DROP AS
        WITH ranked AS (
            SELECT
                id,
                url_hash,
                first_value(id) OVER (
                    PARTITION BY url_hash
                    ORDER BY (storage_path IS NOT NULL) DESC, updated_at DESC, id DESC
                ) AS keeper_id
            FROM media_assets
            WHERE fetch_status <> 'expired'
        )
        SELECT id AS duplicate_id, keeper_id FROM ranked WHERE id <> keeper_id
        """
    )
    op.execute(
        """
        UPDATE item_media AS reference
        SET media_asset_id = dedupe.keeper_id
        FROM media_asset_dedupe AS dedupe
        WHERE reference.media_asset_id = dedupe.duplicate_id
          AND NOT EXISTS (
              SELECT 1
              FROM item_media AS kept
              WHERE kept.content_item_id = reference.content_item_id
                AND kept.media_asset_id = dedupe.keeper_id
                AND kept.role = reference.role
          )
        """
    )
    op.execute(
        """
        DELETE FROM item_media AS reference
        USING media_asset_dedupe AS dedupe
        WHERE reference.media_asset_id = dedupe.duplicate_id
        """
    )
    op.execute(
        """
        UPDATE content_items AS item
        SET primary_image_id = dedupe.keeper_id
        FROM media_asset_dedupe AS dedupe
        WHERE item.primary_image_id = dedupe.duplicate_id
        """
    )
    op.execute(
        """
        DELETE FROM media_assets AS asset
        USING media_asset_dedupe AS dedupe
        WHERE asset.id = dedupe.duplicate_id
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_media_assets_live_url_hash
        ON media_assets (url_hash)
        WHERE fetch_status <> 'expired'
        """
    )
    op.execute("CREATE INDEX ix_media_assets_url_hash ON media_assets (url_hash)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_media_assets_url_hash")
    op.execute("DROP INDEX IF EXISTS uq_media_assets_live_url_hash")
    op.execute("DROP INDEX IF EXISTS uq_identity_source_weak")
