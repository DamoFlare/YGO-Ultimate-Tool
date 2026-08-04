#!/bin/sh
# Starts the Ollama server, waits for it to be ready, then pulls the vision model used by the
# Inspector Agent (services/grading/ai_agent.py) if it isn't already present in the persisted
# volume. Runs on every container start; the pull is skipped (fast) once the model is cached.
set -e

MODEL="${OLLAMA_VISION_MODEL:-llava}"

ollama serve &
SERVER_PID=$!

echo "Waiting for Ollama server to become ready..."
until ollama list >/dev/null 2>&1; do
  sleep 1
done

if ollama list | grep -q "^${MODEL}"; then
  echo "Model '${MODEL}' already present, skipping pull."
else
  echo "Pulling model '${MODEL}' (first run only, this can take a while)..."
  ollama pull "${MODEL}"
fi

wait "${SERVER_PID}"
