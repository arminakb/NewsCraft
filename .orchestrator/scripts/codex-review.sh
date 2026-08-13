#!/usr/bin/env bash
# Cold review of the integrated diff BASE_SHA..HEAD with a fresh, read-only,
# ephemeral Codex session. Requests max effort; falls back to xhigh only if
# the runtime explicitly rejects max. Records requested + effective effort.
set -euo pipefail

base_sha="${1:?Usage: codex-review.sh <base-sha> [run-id]}"
run_id="${2:-$(date -u +%Y%m%dT%H%M%SZ)}"

model="${CODEX_REVIEW_MODEL:-gpt-5.6-sol}"
effort="${CODEX_REVIEW_EFFORT:-max}"
fallback_effort="${CODEX_REVIEW_FALLBACK_EFFORT:-xhigh}"

# Prompts/schemas/output resolve from the script's own kit location so the
# review can target a worktree whose branch predates the framework; the git
# range targets whatever checkout this script is invoked from.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
kit_root="$(dirname "${script_dir}")"
repo_root="$(git rev-parse --show-toplevel)"
cd "${repo_root}"

# Validate the review range before spending a max-effort run on it, and pin
# the exact revisions NOW: the verdict binds to base_sha..head_sha, not to
# whatever HEAD happens to be when the long run finishes.
base_sha="$(git rev-parse --verify "${base_sha}^{commit}" 2>/dev/null)" || {
  echo "Invalid BASE_SHA: ${1}" >&2
  exit 1
}
head_sha="$(git rev-parse HEAD)"
git merge-base --is-ancestor "${base_sha}" "${head_sha}" || {
  echo "BASE_SHA is not an ancestor of HEAD: ${base_sha}" >&2
  exit 1
}

# A dirty tracked tree means the reviewer would read files the verdict's
# commit range does not describe. Fail closed (override consciously with
# CODEX_REVIEW_ALLOW_DIRTY=1 and record why in the ledger).
if [ -n "$(git status --porcelain --untracked-files=no)" ] \
   && [ "${CODEX_REVIEW_ALLOW_DIRTY:-0}" != "1" ]; then
  echo "Tracked worktree is dirty; commit/stash first or set CODEX_REVIEW_ALLOW_DIRTY=1." >&2
  exit 1
fi

# Exclusive run directory: a reused run id must never overwrite evidence.
output_dir="${kit_root}/runs/${run_id}"
mkdir -p "${kit_root}/runs"
if ! mkdir "${output_dir}" 2>/dev/null; then
  output_dir="${kit_root}/runs/${run_id}-$(date -u +%H%M%S)-$$"
  mkdir "${output_dir}"
  echo "Run id already used; writing to ${output_dir}" >&2
fi

# Materialize the prompt from the template, pinned to the exact range.
sed "s/{{BASE_SHA}}/${base_sha}/g; s/{{HEAD_SHA}}/${head_sha}/g" \
  "${kit_root}/prompts/codex-review.md" \
  > "${output_dir}/review-prompt.md"

run_codex() {
  local eff="$1" out_json="$2" events="$3" errlog="$4"
  codex exec \
    -m "${model}" \
    --config "model_reasoning_effort=\"${eff}\"" \
    --sandbox read-only \
    --ephemeral \
    --json \
    --output-schema "${kit_root}/schemas/codex-review.schema.json" \
    --output-last-message "${out_json}" \
    - < "${output_dir}/review-prompt.md" \
    > "${events}" 2> "${errlog}"
}

effective_effort="${effort}"
if ! run_codex "${effort}" "${output_dir}/review.json" \
     "${output_dir}/events.jsonl" "${output_dir}/stderr.log"; then
  if grep -qiE '(unsupported|invalid|unknown|unrecognized).*(effort|reasoning|max)|(effort|reasoning|max).*(unsupported|invalid|unknown|unrecognized)' "${output_dir}/stderr.log"; then
    echo "Effort '${effort}' rejected; preserving failed attempt and retrying at '${fallback_effort}'." >&2
    mv "${output_dir}/stderr.log" "${output_dir}/stderr.${effort}-attempt.log"
    [ -f "${output_dir}/events.jsonl" ] && \
      mv "${output_dir}/events.jsonl" "${output_dir}/events.${effort}-attempt.jsonl"
    effective_effort="${fallback_effort}"
    run_codex "${fallback_effort}" "${output_dir}/review.json" \
      "${output_dir}/events.jsonl" "${output_dir}/stderr.log"
  else
    echo "codex exec failed for a reason unrelated to effort; see ${output_dir}/stderr.log" >&2
    exit 1
  fi
fi

final_head="$(git rev-parse HEAD)"
head_moved_during_review="no"
if [ "${final_head}" != "${head_sha}" ]; then
  head_moved_during_review="yes"
  echo "WARNING: HEAD moved during the review (${head_sha} -> ${final_head}); the verdict binds to ${head_sha} only." >&2
fi

cat > "${output_dir}/review-meta.txt" <<EOF
run_id=${run_id}
base_sha=${base_sha}
head_sha=${head_sha}
head_at_completion=${final_head}
head_moved_during_review=${head_moved_during_review}
model=${model}
requested_effort=${effort}
effective_effort=${effective_effort}
EOF

echo "Review complete: ${output_dir}/review.json (effort: ${effective_effort})"
