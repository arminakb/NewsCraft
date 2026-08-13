#!/usr/bin/env bash
# Create a dedicated branch + worktree for a fresh Codex fixer, based on the
# current HEAD of the integration branch. Prints the worktree path.
set -euo pipefail

run_id="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"

repo_root="$(git rev-parse --show-toplevel)"
worktree="${repo_root}/../codex-fix-${run_id}"
branch="codex/fix-${run_id}"

if git -C "${repo_root}" show-ref --verify --quiet "refs/heads/${branch}"; then
  echo "Branch ${branch} already exists; pass a different run-id." >&2
  exit 1
fi

git -C "${repo_root}" worktree add -b "${branch}" "${worktree}" HEAD >&2
echo "${worktree}"
