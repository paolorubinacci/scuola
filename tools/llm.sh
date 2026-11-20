#!/bin/bash
# Avvia un modello aperto (Qwen2.5 7B Instruct) con Ollama su http://127.0.0.1:11434 — per i riassunti del diario senza chiave Claude.
set -e
mkdir -p ~/llm/models
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh >/dev/null
sudo systemctl stop ollama 2>/dev/null || true
export OLLAMA_MODELS="$HOME/llm/models" OLLAMA_HOST=127.0.0.1:11434
nohup ollama serve > ~/llm/server.log 2>&1 &
for i in $(seq 1 60); do curl -sf http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done
ollama pull "${LOCAL_MODEL:-qwen2.5:7b}" 2>&1 | tail -1
echo "modello pronto"
