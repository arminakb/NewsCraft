from pathlib import Path

from app.db.model_registry import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SECURITY_MIGRATION = BACKEND_ROOT / "alembic/versions/0012_security_foundation.py"
PROVIDER_MIGRATION = BACKEND_ROOT / "alembic/versions/0013_generic_llm_providers.py"


def test_encrypted_secret_migration_matches_required_model_schema():
    security_source = SECURITY_MIGRATION.read_text(encoding="utf-8")
    provider_source = PROVIDER_MIGRATION.read_text(encoding="utf-8")
    secret_table = Base.metadata.tables["encrypted_secrets"]
    provider_table = Base.metadata.tables["llm_providers"]

    assert set(secret_table.columns.keys()) == {
        "id",
        "purpose",
        "owner_type",
        "owner_id",
        "ciphertext",
        "nonce",
        "key_version",
        "created_at",
        "last_rotated_at",
    }
    assert 'op.create_table(\n        "encrypted_secrets"' in security_source
    assert "ck_encrypted_secrets_ciphertext_length" in security_source
    assert "ck_encrypted_secrets_nonce_length" in security_source
    assert "uq_encrypted_secret_owner_purpose" in security_source
    assert "ix_encrypted_secrets_key_version" in security_source

    secret_foreign_key = next(iter(provider_table.c.secret_id.foreign_keys))
    assert secret_foreign_key.target_fullname == "encrypted_secrets.id"
    assert secret_foreign_key.ondelete == "RESTRICT"
    assert 'sa.ForeignKeyConstraint(["secret_id"], ["encrypted_secrets.id"], ondelete="RESTRICT")' in provider_source
    assert "uq_llm_providers_secret_id" in provider_source


def test_later_provider_migration_preserves_encrypted_secret_records():
    provider_source = PROVIDER_MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "0012_security_foundation"' in provider_source
    assert "DROP TABLE ENCRYPTED_SECRETS" not in provider_source.upper()
    assert "DELETE FROM ENCRYPTED_SECRETS" not in provider_source.upper()
