#!/usr/bin/env bash
# Bootstraps the local LLM (Ollama + gemma4:e2b) and runs the orchestrator.
#
# Env vars:
#   LLM_PROVIDER    "ollama" (default) or "openai" — skip ollama bootstrap if openai
#   LLM_MODEL       defaults to gemma4:e2b for ollama
#   OLLAMA_BASE_URL defaults to http://localhost:11434

set -euo pipefail

PROVIDER="${LLM_PROVIDER:-ollama}"
MODEL="${LLM_MODEL:-gemma4:e2b}"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"

if [[ "$PROVIDER" == "ollama" ]]; then
    echo "[start] provider=ollama model=$MODEL"

    if ! command -v ollama >/dev/null 2>&1; then
        echo "[start] error: ollama not installed — https://ollama.com" >&2
        exit 1
    fi

    if ! curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
        echo "[start] starting ollama daemon..."
        nohup ollama serve >/tmp/ollama.log 2>&1 &
        for _ in $(seq 1 30); do
            if curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
                break
            fi
            sleep 0.5
        done
        if ! curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
            echo "[start] error: ollama daemon failed to start; see /tmp/ollama.log" >&2
            exit 1
        fi
    fi

    if ! ollama list | awk 'NR>1 {print $1}' | grep -qx "$MODEL"; then
        echo "[start] pulling $MODEL ..."
        ollama pull "$MODEL"
    fi

    echo "[start] warming $MODEL ..."
    curl -fsS "${OLLAMA_URL}/api/generate" \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"$MODEL\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_predict\":1}}" \
        >/dev/null
else
    echo "[start] provider=$PROVIDER (skipping ollama bootstrap)"
fi

echo "[start] running pipeline..."
if command -v uv >/dev/null 2>&1; then
    exec uv run python -m orchestrator.api.run
else
    exec python -m orchestrator.api.run
fi
