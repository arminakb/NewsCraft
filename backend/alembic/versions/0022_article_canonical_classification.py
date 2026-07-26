"""materialize canonical article classification

Revision ID: 0022_article_canonical_classification
Revises: 0021_editorial_state_contracts
"""

from alembic import op

revision = "0022_article_canonical_classification"
down_revision = "0021_editorial_state_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION newscraft_canonical_article_classification(
          raw_content_type text,
          raw_topic text,
          raw_language text
        ) RETURNS jsonb
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
          WITH normalized AS (
            SELECT
              lower(nullif(regexp_replace(btrim(raw_content_type), '\s+', ' ', 'g'), '')) AS content_type,
              lower(nullif(regexp_replace(btrim(raw_topic), '\s+', ' ', 'g'), '')) AS topic,
              lower(nullif(regexp_replace(btrim(raw_language), '\s+', ' ', 'g'), '')) AS language
          ),
          canonical AS (
            SELECT
              content_type,
              CASE topic
                WHEN 'ai' THEN 'AI'
                WHEN 'economy' THEN 'Economy'
                WHEN 'news' THEN 'News'
                WHEN 'tech' THEN 'Tech'
                WHEN 'general' THEN NULL
                ELSE topic
              END AS topic,
              language
            FROM normalized
          ),
          promoted AS (
            SELECT
              CASE WHEN content_type = 'article' AND topic = 'News' THEN 'news' ELSE content_type END AS content_type,
              topic,
              language
            FROM canonical
          )
          SELECT jsonb_build_object(
            'content_type', content_type,
            'topic', CASE
              WHEN content_type IS NOT NULL
                AND topic IS NOT NULL
                AND lower(content_type) = lower(topic)
              THEN NULL
              ELSE topic
            END,
            'language', language
          )
          FROM promoted
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE content_items
        ADD COLUMN canonical_classification jsonb
        GENERATED ALWAYS AS (
          newscraft_canonical_article_classification(
            content_type,
            metrics -> 'classification' ->> 'category',
            language_code
          )
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_content_items_canonical_content_type
        ON content_items ((canonical_classification ->> 'content_type'))
        """
    )
    op.execute(
        """
        CREATE INDEX ix_content_items_canonical_topic
        ON content_items ((canonical_classification ->> 'topic'))
        """
    )
    op.execute(
        """
        CREATE INDEX ix_content_items_canonical_language
        ON content_items ((canonical_classification ->> 'language'))
        """
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_canonical_language", table_name="content_items")
    op.drop_index("ix_content_items_canonical_topic", table_name="content_items")
    op.drop_index("ix_content_items_canonical_content_type", table_name="content_items")
    op.drop_column("content_items", "canonical_classification")
    op.execute("DROP FUNCTION newscraft_canonical_article_classification(text, text, text)")
