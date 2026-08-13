#!/usr/bin/env bash
# Run a fresh, ephemeral Codex fixer inside a dedicated worktree.
# The prompt file must already contain ONLY orchestrator-ACCEPTED findings
# (build it from .orchestrator/prompts/codex-fix-header.md).
set -euo pipefail

worktree="${1:?Usage: codex-fix.sh <fixer-worktree-path> <fix-prompt-file> <expected-base-sha> [run-id]}"
prompt_file="${2:?Usage: codex-fix.sh <fixer-worktree-path> <fix-prompt-file> <expected-base-sha> [run-id]}"
expected_base="${3:?Usage: codex-fix.sh <fixer-worktree-path> <fix-prompt-file> <expected-base-sha> [run-id]}"
run_id="${4:-$(date -u +%Y%m%dT%H%M%SZ)}"

model="${CODEX_FIX_MODEL:-gpt-5.6-sol}"
effort="${CODEX_FIX_EFFORT:-max}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
kit_root="$(dirname "${script_dir}")"

prompt_abs="$(cd "$(dirname "${prompt_file}")" && pwd)/$(basename "${prompt_file}")"
schema_abs="${kit_root}/schemas/codex-fix.schema.json"

cd "${worktree}"

# A workspace-write fixer must only ever run in a dedicated, clean worktree
# sitting exactly on the expected base — never in the integration checkout.
wt_top="$(git rev-parse --show-toplevel)"
main_top="$(dirname "${kit_root}")"
if [ "${wt_top}" = "${main_top}" ]; then
  echo "Refusing to run the fixer inside the main checkout (${main_top})." >&2
  exit 1
fi
wt_head="$(git rev-parse HEAD)"
expected_base="$(git rev-parse --verify "${expected_base}^{commit}")" || exit 1
if [ "${wt_head}" != "${expected_base}" ]; then
  echo "Worktree HEAD ${wt_head} != expected base ${expected_base}; refusing." >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "Fixer worktree is not clean; refusing." >&2
  exit 1
fi

# Exclusive run directory: never overwrite prior evidence.
output_dir="${kit_root}/runs/${run_id}"
mkdir -p "${kit_root}/runs"
if ! mkdir "${output_dir}" 2>/dev/null; then
  output_dir="${kit_root}/runs/${run_id}-$(date -u +%H%M%S)-$$"
  mkdir "${output_dir}"
  echo "Run id already used; writing to ${output_dir}" >&2
fi
{
  echo "worktree=${wt_top}"
  echo "expected_base=${expected_base}"
  echo "pre_head=${wt_head}"
} > "${output_dir}/fix-meta.txt"

codex exec \
  -m "${model}" \
  --config "model_reasoning_effort=\"${effort}\"" \
  --sandbox workspace-write \
  --ephemeral \
  --json \
  --output-schema "${schema_abs}" \
  --output-last-message "${output_dir}/fix.json" \
  - < "${prompt_abs}" \
  > "${output_dir}/fix-events.jsonl" 2> "${output_dir}/fix-stderr.log"

echo "post_head=$(git rev-parse HEAD)" >> "${output_dir}/fix-meta.txt"
echo "Fix complete: ${output_dir}/fix.json"
echo "Inspect the diff in ${worktree} before integrating."
