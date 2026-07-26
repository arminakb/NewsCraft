#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$repo_root/scripts/test_postgres.sh" \
  tests/stories/test_manual_intake_postgres.py::test_two_session_manual_replay_serializes_to_one_complete_materialization \
  tests/stories/test_repository.py::test_group_content_items_reuses_story_and_captures_one_snapshot_per_hash \
  tests/integration/test_editorial_research_generation_flow.py::test_http_manual_story_research_generation_edit_and_exact_approval \
  tests/integration/test_multiplatform_export_flow.py::test_four_platform_pack_exports_and_manual_completion \
  tests/postgres/test_telegram_publish_service.py::test_concurrent_publish_claim_sends_once_and_creates_one_publication \
  tests/integration/test_publish_crash_recovery.py::test_crash_after_remote_send_requires_reconciliation_and_replay_does_not_duplicate \
  tests/integration/test_worker_crash_recovery.py::test_worker_death_after_claim_requeues_one_lease_and_runs_handler_once
