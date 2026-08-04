"""
Inspector Agent: local Vision-Language Model surface analysis for card grading.

Receives the already cropped/normalized card image from the Geometric Agent and judges surface
defects (scratches, creases) that a deterministic algorithm can't reliably assess. Talks to a
locally self-hosted Ollama server (see docker-compose.yml) running the `llava` model — no
external API keys, no data leaves the machine.
"""
import json
from typing import Any, Dict

import cv2
import numpy as np
from ollama import AsyncClient, ResponseError

import config


class InspectorAgentError(Exception):
    """Raised when the local VLM can't be reached or returns an unusable response."""


class InspectorAgent:
    """Async client wrapper around the local Ollama `llava` model."""

    def __init__(self, base_url: str = config.OLLAMA_BASE_URL, model: str = config.OLLAMA_VISION_MODEL):
        self.model = model
        self._client = AsyncClient(host=base_url)

    async def analyze_surface(self, normalized_img: np.ndarray) -> Dict[str, Any]:
        """Send the normalized card image to the VLM and return the parsed defect JSON."""
        ok, buffer = cv2.imencode(".jpg", normalized_img)
        if not ok:
            raise InspectorAgentError("Failed to encode normalized image for the VLM request.")

        try:
            response = await self._client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": config.INSPECTOR_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": "Analyze this card's surface for scratches and creases.",
                        "images": [buffer.tobytes()],
                    },
                ],
                format="json",
                options={"temperature": 0.1},
            )
        except ResponseError as e:
            raise InspectorAgentError(
                f"Ollama returned an error (is the '{self.model}' model pulled? "
                f"See docker-compose.yml): {e}"
            ) from e
        except Exception as e:
            raise InspectorAgentError(
                f"Could not reach the local Ollama server at {config.OLLAMA_BASE_URL}. "
                f"Run `docker compose up -d` and try again. Original error: {e}"
            ) from e

        raw_content = response["message"]["content"]
        try:
            data = json.loads(raw_content)
        except (json.JSONDecodeError, TypeError) as e:
            raise InspectorAgentError(f"VLM returned non-JSON content: {raw_content!r}") from e

        return {
            "has_scratches": bool(data.get("has_scratches", False)),
            "scratch_severity": data.get("scratch_severity", "none") or "none",
            "has_creases": bool(data.get("has_creases", False)),
            "crease_severity": data.get("crease_severity", "none") or "none",
            "details": data.get("details", ""),
        }

    async def close(self) -> None:
        """No persistent session to close for the Ollama AsyncClient; kept for API symmetry."""
        return None
