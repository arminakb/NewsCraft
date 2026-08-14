"""persist canonical evidence source identity and primary flag

Revision ID: 0029_wave2a_ops
Revises: 0035_feed_clear

The SQL coverage filter used to re-derive the source identity from
``source_url`` with ``split_part``, which cannot reproduce the IDNA and public
suffix reduction performed by ``app.research.completeness``. Persisting the
canonical values lets both rules read the same data.
"""

from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import idna
import sqlalchemy as sa
import tldextract
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0037_wave2a_ops"
down_revision = "0036_wave2a_ingest"
branch_labels = None
depends_on = None

_BACKFILL_BATCH = 500

_snapshots = sa.table(
    "story_evidence_snapshots",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("source_url", sa.Text()),
    sa.column("snapshot_metadata", postgresql.JSONB()),
    sa.column("source_identity", sa.Text()),
    sa.column("is_primary", sa.Boolean()),
)


_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)


def _registrable_host(url: str) -> str | None:
    """Frozen copy of app.research.completeness._registrable_host at this revision.

    Migrations never import application code, so the backfill carries its own
    copy of the rule that produced the values being persisted.
    """

    try:
        host = (urlsplit(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return None
    if not host:
        return None
    try:
        return str(ip_address(host))
    except ValueError:
        pass
    try:
        host = idna.encode(host, uts46=True).decode("ascii").lower()
    except idna.IDNAError:
        return None
    return _TLD_EXTRACT(host).top_domain_under_public_suffix or host


def _source_identity(source_url: Any, snapshot_metadata: Any) -> str | None:
    url = source_url if isinstance(source_url, str) else None
    host = _registrable_host(url) if url else None
    if host:
        return f"host:{host}"
    label = (snapshot_metadata or {}).get("source_label")
    identity = label.strip().casefold() if isinstance(label, str) else ""
    return f"source:{identity}" if identity else None


def _is_primary(snapshot_metadata: Any) -> bool:
    return bool((snapshot_metadata or {}).get("is_primary"))


def upgrade() -> None:
    op.add_column("story_evidence_snapshots", sa.Column("source_identity", sa.Text(), nullable=True))
    op.add_column(
        "story_evidence_snapshots",
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(_snapshots.c.id, _snapshots.c.source_url, _snapshots.c.snapshot_metadata)
    ).all()
    if not rows:
        return
    update = (
        _snapshots.update()
        .where(_snapshots.c.id == sa.bindparam("snapshot_id"))
        .values(
            source_identity=sa.bindparam("identity", type_=sa.Text()),
            is_primary=sa.bindparam("primary_flag", type_=sa.Boolean()),
        )
    )
    payload = [
        {
            "snapshot_id": row.id,
            "identity": _source_identity(row.source_url, row.snapshot_metadata),
            "primary_flag": _is_primary(row.snapshot_metadata),
        }
        for row in rows
    ]
    for start in range(0, len(payload), _BACKFILL_BATCH):
        connection.execute(update, payload[start : start + _BACKFILL_BATCH])


def downgrade() -> None:
    op.drop_column("story_evidence_snapshots", "is_primary")
    op.drop_column("story_evidence_snapshots", "source_identity")
