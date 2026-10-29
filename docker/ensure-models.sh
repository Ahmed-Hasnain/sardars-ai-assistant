#!/bin/sh
set -eu

: "${SARDARS_OLLAMA_MODEL:?Set the chat model name}"

ensure_model() {
    if ! ollama show "$1" >/dev/null 2>&1; then
        ollama pull "$1"
    fi
}

ensure_model "$SARDARS_OLLAMA_MODEL"
ensure_model "${SARDARS_PROTOTYPE_CHAT_MODEL:-qwen3:0.6b}"
ensure_model qwen3-embedding:0.6b
