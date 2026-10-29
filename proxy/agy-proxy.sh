#!/usr/bin/env bash
# Run agy (Antigravity CLI) with tool use against this LiteLLM proxy (nemotron-3-ultra via agy's built-in Gemini model names).
# Usage: proxy/agy-proxy.sh [agy args...]       e.g.  scripts/agy-proxy.sh        (interactive)
#                                                       scripts/agy-proxy.sh -p "..."
# How: agy's Gemini-API route is the only one that sends tool declarations. It needs `modelProvider: "gemini"` in
# ~/.gemini/antigravity-cli/settings.json; this script sets it for the session and restores it on exit.
# agy can only request its own Gemini model names; litellm_config.yaml (router_settings.model_group_alias) routes them to
# nemotron-3-ultra, and agy_callbacks.py fixes agy's tool-result role (otherwise the model re-runs the same command).
set -euo pipefail
# where the openai-proxy checkout lives (its .env holds the proxy key; its litellm_config.yaml must carry the agy settings)
DIR="${PROXY_DIR:-$HOME/workarea/fox/openai-proxy}"
# read ONLY the proxy key: .env also holds the upstream provider keys (OpenRouter, Gemini, xAI), which agents must never see
LITELLM_MASTER_KEY="$(grep -m1 '^LITELLM_MASTER_KEY=' "$DIR/.env" | cut -d= -f2- | tr -d '"')"
[ -n "$LITELLM_MASTER_KEY" ] || { echo "LITELLM_MASTER_KEY not found in $DIR/.env" >&2; exit 1; }
URL="${PROXY_URL:-http://localhost:8000}"
SETTINGS="$HOME/.gemini/antigravity-cli/settings.json"

curl -sf "$URL/health/liveliness" >/dev/null || { echo "proxy not reachable at $URL (run 'make up')" >&2; exit 1; }
grep -q agy_callbacks "$DIR/litellm_config.yaml" \
  || { echo "litellm_config.yaml lacks the agy callback/alias config (see agy_callbacks.py)" >&2; exit 1; }

# set modelProvider for this session only; restore the previous value (or remove it) on exit
ORIG="$(python3 - "$SETTINGS" <<'P'
import json,sys
p=sys.argv[1]; s=json.load(open(p)); print(json.dumps(s.get("modelProvider")))
s["modelProvider"]="gemini"; json.dump(s,open(p,"w"),indent=2)
P
)"
restore() { python3 - "$SETTINGS" "$ORIG" <<'P'
import json,sys
p,o=sys.argv[1],json.loads(sys.argv[2]); s=json.load(open(p))
s.pop("modelProvider",None) if o is None else s.__setitem__("modelProvider",o)
json.dump(s,open(p,"w"),indent=2)
P
}
trap restore EXIT

unset AGY_LLM_GATEWAY_URL AGY_LLM_GATEWAY_API_KEY AGY_LLM_GATEWAY_WIRE_PROTOCOL AGY_LLM_GATEWAY_MODELS
export GEMINI_API_KEY="$LITELLM_MASTER_KEY" GOOGLE_GEMINI_BASE_URL="$URL"
case " $* " in *" --model "*) agy "$@" ;; *) agy --model gemini-3.8-flash-medium "$@" ;; esac
