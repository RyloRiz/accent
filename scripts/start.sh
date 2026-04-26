#!/usr/bin/env bash
# Bootstraps the local LLM (Ollama + gemma4:e2b) and runs the orchestrator.
#
# Env vars:
#   MODE            "run" (default) one-shot pipeline test, or "serve" FastAPI server
#   LLM_PROVIDER    "ollama" (default) or "openai" — skip ollama bootstrap if openai
#   LLM_MODEL       defaults to gemma4:e2b for ollama
#   OLLAMA_BASE_URL defaults to http://localhost:11434
#   ACCENT_HOST     serve mode bind host, defaults to 127.0.0.1
#   ACCENT_PORT     serve mode bind port, defaults to 8765

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

MODE="${MODE:-serve}"
case "$MODE" in
    serve)
        TARGET="orchestrator.api.server"
        echo "[start] serving API on ${ACCENT_HOST:-127.0.0.1}:${ACCENT_PORT:-8765}"
        ;;
    run)
        TARGET="orchestrator.api.run"
        echo "[start] running pipeline..."
        ;;
    *)
        echo "[start] error: unknown MODE=$MODE (expected 'run' or 'serve')" >&2
        exit 1
        ;;
esac

if command -v uv >/dev/null 2>&1; then
    exec env PYTHONPATH=src uv run python -m "$TARGET"
else
    exec env PYTHONPATH=src python -m "$TARGET"
fi
