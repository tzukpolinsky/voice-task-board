from __future__ import annotations

import base64
import json
import logging
import re
import struct

import httpx
from pydantic import ValidationError

from voice_task_board.intent import FirstPassIntent, ResolvedIntent
from voice_task_board.prompts import load_prompt


logger = logging.getLogger(__name__)


class GeminiBackend:
    _model: str | None = None
    _endpoint: str | None = None

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._verify_and_set_model(api_key)
    
    def _verify_and_set_model(self, api_key: str) -> None:
        """Verify the model ID is available; update _model and _endpoint if needed."""
        if GeminiBackend._model is not None:
            return
        
        try:
            response = httpx.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            
            model_ids = [m.get("name", "").split("/")[-1] for m in models]
            logger.info(f"Available models: {model_ids}")
            
            GeminiBackend._model = self._pick_best_model(model_ids)
            if not GeminiBackend._model:
                GeminiBackend._model = "gemini-2.0-flash"
            
            GeminiBackend._endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GeminiBackend._model}:generateContent"
            logger.info(f"Using model: {GeminiBackend._model}")
        except Exception as e:
            logger.warning(f"Failed to verify model, using default: {e}")
            GeminiBackend._model = "gemini-2.0-flash"
            GeminiBackend._endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GeminiBackend._model}:generateContent"
    @staticmethod
    def _pick_best_model(model_ids: list[str]) -> str | None:
        """Pick the highest-version general-purpose flash model that handles audio + text."""
        EXCLUDED = ("tts", "lite", "live", "image", "embedding", "vision", "tuning",
                    "thinking", "computer-use", "robotics", "deep-research", "video",
                    "veo", "imagen", "lyria", "antigravity", "aqa", "gemma")
        candidates = []
        for model_id in model_ids:
            lower = model_id.lower()
            if "flash" not in lower or "gemini" not in lower:
                continue
            if any(x in lower for x in EXCLUDED):
                continue
            candidates.append(model_id)

        if not candidates:
            return None

        def sort_key(m: str) -> tuple[int, int, int]:
            """Higher version wins; stable releases beat previews."""
            match = re.search(r'(\d+)\.(\d+)', m)
            major, minor = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
            stable = 0 if "preview" in m.lower() else 1
            return (major, minor, stable)

        candidates.sort(key=sort_key, reverse=True)
        return candidates[0]
    
    def extract_intent(self, pcm_bytes: bytes, categories: list[str]) -> FirstPassIntent:
        if not pcm_bytes:
            raise ValueError("empty audio")

        wav_bytes = self._wrap_pcm_as_wav(pcm_bytes)
        wav_b64 = base64.b64encode(wav_bytes).decode("utf-8")

        categories_json = json.dumps(categories, ensure_ascii=False)
        system_prompt = load_prompt("intent_extraction").format(categories=categories_json)

        request_body = {
            "contents": [{
                "parts": [
                    {"inlineData": {"mimeType": "audio/wav", "data": wav_b64}},
                    {"text": system_prompt},
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add", "else"]},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "category": {"type": "string"},
                        "transcription": {"type": "string"},
                    },
                    "required": ["action", "title", "category", "transcription"],
                },
            },
        }

        text = self._post_and_extract_text(request_body)
        try:
            intent = FirstPassIntent(**json.loads(text))
            logger.info(f"Layer-1 intent: action={intent.action!r} title={intent.title!r} category={intent.category!r}")
            logger.debug(f"Layer-1 transcription: {intent.transcription!r}")
            return intent
        except (ValidationError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse layer-1 response: {e}; raw={text!r}")
            raise

    def resolve_else(self, transcription: str, tasks: list[dict]) -> ResolvedIntent:
        """Layer-2: given the transcription and current task list, decide edit/delete/unknown + which target."""
        tasks_json = json.dumps(tasks, ensure_ascii=False, indent=2)
        system_prompt = load_prompt("resolve_else").format(
            transcription=transcription,
            tasks=tasks_json,
        )

        request_body = {
            "contents": [{"parts": [{"text": system_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["edit", "delete", "unknown"]},
                        "target_id": {"type": "integer", "nullable": True},
                        "title": {"type": "string", "nullable": True},
                        "content": {"type": "string", "nullable": True},
                        "category": {"type": "string", "nullable": True},
                    },
                    "required": ["action"],
                },
            },
        }

        text = self._post_and_extract_text(request_body)
        try:
            resolved = ResolvedIntent(**json.loads(text))
            logger.info(f"Layer-2 resolved: action={resolved.action!r} target_id={resolved.target_id}")
            return resolved
        except (ValidationError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse layer-2 response: {e}; raw={text!r}")
            raise

    def _post_and_extract_text(self, request_body: dict) -> str:
        try:
            response = httpx.post(
                GeminiBackend._endpoint,
                params={"key": self._api_key},
                json=request_body,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            logger.error(f"Gemini API error: {e}")
            raise

        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No candidates in Gemini response")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise ValueError("No parts in Gemini response")
        return parts[0].get("text", "{}")

    @staticmethod
    def _wrap_pcm_as_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        subchunk2_size = len(pcm_bytes)

        wav_header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + subchunk2_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            subchunk2_size,
        )
        return wav_header + pcm_bytes
