#!/usr/bin/env bash
# Apply the upstream Hermes fix NousResearch/hermes-agent#135354 to a git install of Hermes Agent, until
# it is merged. Without it, a subagent whose first answer misses its output_schema gets ONE correction
# turn that starts from an empty conversation: it no longer sees its task, its tool results or its own
# answer, so it guesses (we measured answers of 0, a sibling's result, and the sum of every file).
#   bash hermes/patch_hermes.sh            # auto-detects the install behind `hermes`
#   HERMES_SRC=/path/to/hermes-agent bash hermes/patch_hermes.sh
# Safe to re-run: does nothing if the fix is already present (patched here, or merged upstream).
# `hermes update` keeps local changes (autostash); re-run this after updating to be sure.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
P="$ROOT/hermes/patches/delegate-schema-retry-keeps-history.patch"
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
# Find the Hermes install. The official installer puts the `hermes` launcher in ~/.local/bin but only adds
# that to PATH for interactive shells, so also look there (and honour HERMES_BIN / HERMES_SRC).
src="${HERMES_SRC:-}"
if [[ -z "$src" ]]; then
  for cand in "${HERMES_BIN:-}" "$(command -v hermes 2>/dev/null || true)" "$HOME/.local/bin/hermes"; do
    [[ -n "$cand" && -x "$cand" ]] || continue
    src="$("$cand" --version 2>/dev/null | sed -n 's/^Install directory: //p' | head -1 || true)"
    [[ -n "$src" ]] && break
  done
fi
if [[ -z "$src" && -f "$HOME/.hermes/hermes-agent/tools/delegate_tool_child_run.py" ]]; then src="$HOME/.hermes/hermes-agent"; fi
[[ -n "$src" && -f "$src/tools/delegate_tool_child_run.py" ]] || die "Hermes source not found; set HERMES_SRC to your hermes-agent checkout (the directory 'hermes --version' lists as Install directory)"
echo "Hermes source: $src"
f="$src/tools/delegate_tool_child_run.py"
if grep -q "conversation_history=_history" "$f"; then echo "Hermes at $src already has the schema-retry fix; nothing to do."; exit 0; fi
if ! grep -q "user_message=build_retry_message(_schema_errors), task_id=child_task_id," "$f"; then
  die "Hermes at $src changed this code path; check whether NousResearch/hermes-agent#135354 (or an equivalent fix) is merged before patching by hand"
fi
git -C "$src" apply --check "$P" || die "patch does not apply cleanly to $src"
git -C "$src" apply "$P"
grep -q "conversation_history=_history" "$f" || die "patch applied but the fix is not present"
echo "Applied NousResearch/hermes-agent#135354 to $src"
