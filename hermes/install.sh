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
umask 077; touch "$H/.env"
grep -v '^MINICPM_API_KEY=' "$H/.env" > "$H/.env.tmp" || true
echo "MINICPM_API_KEY=$key" >> "$H/.env.tmp"; mv "$H/.env.tmp" "$H/.env"; chmod 600 "$H/.env"
say "Hermes profile ready at $H"
echo "Run:  HERMES_HOME=$H hermes"
