from __future__ import annotations

from uuid import UUID

from app.retention.filesystem import _classified_media_claims


def test_batch_claim_classification_matches_the_row_by_row_safety_rules(tmp_path):
    media_root = tmp_path / "media"
    (media_root / "2026").mkdir(parents=True)
    canonical_file = media_root / "2026" / "canonical.jpg"
    canonical_file.write_bytes(b"canonical")
    alias = media_root / "2026" / "alias.jpg"
    alias.symlink_to(canonical_file)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")

    plain_id = UUID(int=1)
    alias_id = UUID(int=2)
    escaping_id = UUID(int=3)
    missing_id = UUID(int=4)

    canonical_paths, deletion_authorized, unclassifiable = _classified_media_claims(
        media_root,
        [
            (plain_id, "2026/canonical.jpg"),
            (alias_id, "2026/alias.jpg"),
            (escaping_id, str(outside)),
            (missing_id, "2026/missing.jpg"),
        ],
    )

    assert canonical_paths[plain_id] == "2026/canonical.jpg"
    assert plain_id in deletion_authorized
    # The alias resolves to a protected canonical claim but is never deletable.
    assert canonical_paths[alias_id] == "2026/canonical.jpg"
    assert alias_id not in deletion_authorized
    # A path outside the owned root is never classified and taints the batch.
    assert escaping_id not in canonical_paths
    assert escaping_id not in deletion_authorized
    assert unclassifiable is True
    # A missing file still has a stable identity and stays deletable.
    assert canonical_paths[missing_id] == "2026/missing.jpg"
    assert missing_id in deletion_authorized
