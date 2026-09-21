#!/usr/bin/env bash
set -euo pipefail
if [ "${NODE_RANK:?}" = 0 ]; then
  # Validate before loading weights. The key never becomes a vLLM env/CLI value.
  python3 -c 'from glm_private_auth import BearerMiddleware; BearerMiddleware(None); print("Private API key preflight passed")'
fi
unset VLLM_API_KEY
exec bash /start.sh "$@"
