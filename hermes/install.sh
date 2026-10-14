#!/usr/bin/env bash
# Install the two-model config into a Hermes profile (default: a dedicated HERMES_HOME so your main
# ~/.hermes is untouched). Writes MINICPM_API_KEY to that profile's .env (0600).
#   bash hermes/install.sh                         # -> ~/.hermes-twomodel
#   HERMES_HOME=~/.hermes bash hermes/install.sh   # into your main profile (backs up config.yaml first)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/bin/env.sh"
H="${HERMES_HOME:-$HOME/.hermes-twomodel}"
mkdir -p "$H"
key="$(mini_key)"; [[ -n "$key" ]] || die "no MiniCPM key at $MINI_STATE/api_tokens.yml; run bin/up.sh once first"
if [[ -f "$H/config.yaml" ]]; then cp "$H/config.yaml" "$H/config.yaml.bak-$(date +%Y%m%d%H%M%S)"; fi
sed -e "s#127.0.0.1:8899#127.0.0.1:$QWEN_PORT#" -e "s#127.0.0.1:8898#127.0.0.1:$MINI_PORT#" \
    -e "s#max_concurrent_children: 8#max_concurrent_children: $MINI_MAX_BATCH#" "$ROOT/hermes/config.yaml" > "$H/config.yaml"
# Delegation guidance for the main agent, kept between markers in the profile's SOUL.md so re-running this
# script replaces it instead of appending a second copy. Your own SOUL.md text outside the markers is kept.
begin="<!-- twomodels-onespark:delegation:begin -->"; end="<!-- twomodels-onespark:delegation:end -->"
soul="$H/SOUL.md"; touch "$soul"
python3 - "$soul" "$ROOT/hermes/delegation-guidance.md" "$begin" "$end" <<'PY'
import re, sys
soul, guide, b, e = sys.argv[1:5]
text = open(soul, encoding="utf-8").read()
text = re.sub(re.escape(b) + r".*?" + re.escape(e) + r"\n?", "", text, flags=re.S).rstrip()
block = f"{b}\n{open(guide, encoding='utf-8').read().strip()}\n{e}\n"
open(soul, "w", encoding="utf-8").write((text + "\n\n" if text else "") + block)
PY
umask 077; touch "$H/.env"
grep -v '^MINICPM_API_KEY=' "$H/.env" > "$H/.env.tmp" || true
echo "MINICPM_API_KEY=$key" >> "$H/.env.tmp"; mv "$H/.env.tmp" "$H/.env"; chmod 600 "$H/.env"
say "Hermes profile ready at $H"
echo "Run:  HERMES_HOME=$H hermes"
