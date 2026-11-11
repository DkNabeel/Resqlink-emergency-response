"""Groq-powered emergency report classification with a local NLP fallback."""
import json
import os
import re

import httpx

ALLOWED_TYPES = {
    "fire", "flood", "earthquake", "cyclone", "landslide", "tsunami",
    "lightning", "gas_leak", "medical", "road_accident", "violence", "unknown",
}
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIServiceError(RuntimeError):
    """Groq unavailable or returned an invalid classification."""


def parse_classification(text):
    if not isinstance(text, str) or not text.strip():
        raise AIServiceError("AI provider returned an empty response.")
    cleaned = text.strip()
    cleaned = re.sub(r"^\s*```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIServiceError("AI provider did not return valid JSON.") from exc
    if not isinstance(payload, dict):
        raise AIServiceError("AI response must be a JSON object.")

    emergency_type = str(payload.get("emergency_type", "unknown")).strip().lower()
    if emergency_type not in ALLOWED_TYPES:
        emergency_type = "unknown"
    confidence = str(payload.get("confidence", "low")).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    details = payload.get("key_details", [])
    if not isinstance(details, list):
        details = []
    return {
        "emergency_type": emergency_type,
        "confidence": confidence,
        "short_summary": str(payload.get("short_summary", "")).strip()[:240],
        "key_details": [str(item).strip()[:100] for item in details[:5] if str(item).strip()],
    }


def _prompt(message, language, local_type):
    return (
        "Classify this emergency report for ResQLink in India. Respond with one valid JSON object only "
        "containing emergency_type, confidence, short_summary, and key_details. "
        f"emergency_type must be one of {sorted(ALLOWED_TYPES)}. "
        "confidence must be high, medium, or low. Keep short_summary under 240 characters. "
        "key_details must be an array of up to five short factual items. "
        "Do not provide safety instructions, medical diagnoses, reassurance, or safe-location claims. "
        "Do not invent places, people, injuries, causes, or coordinates. "
        f"Write the summary and key details in language code {language}. "
        f"Local keyword detector hint: {local_type}. If the report is vague, use unknown and low confidence.\n"
        f"Emergency report:\n{message.strip()}"
    )


def analyze_emergency_with_groq(message, language="en", local_type="unknown"):
    """Classify using Groq; try one configured fallback model on transient/model errors."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string.")
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise AIServiceError("GROQ_API_KEY is not configured.")

    primary = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
    fallback = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b").strip()
    try:
        timeout_seconds = max(8.0, min(25.0, float(os.getenv("GROQ_REQUEST_TIMEOUT_SECONDS", "14"))))
    except ValueError:
        timeout_seconds = 14.0

    models = list(dict.fromkeys(model for model in (primary, fallback) if model))
    failures = []
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    for index, model in enumerate(models):
        try:
            response = httpx.post(
                GROQ_CHAT_URL,
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a careful emergency-report classifier. Never invent facts. Return JSON only.",
                        },
                        {"role": "user", "content": _prompt(message, language, local_type)},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 300,
                },
                timeout=timeout_seconds,
            )
            if response.status_code >= 400:
                detail = response.text[:240].replace(api_key, "[REDACTED]")
                raise RuntimeError(f"HTTP {response.status_code}: {detail}")
            body = response.json()
            text = body["choices"][0]["message"]["content"]
            parsed = parse_classification(text)
            return {
                "status": "connected",
                "provider": "Groq API",
                "model": model,
                **parsed,
            }
        except AIServiceError:
            raise
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            detail = str(exc).replace(api_key, "[REDACTED]")[:300]
            failures.append(f"{model}: {detail}")
            retryable = (
                isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))
                or any(code in detail for code in ("HTTP 404", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504"))
                or status_code in {404, 500, 502, 503, 504}
            )
            if not (retryable and index + 1 < len(models)):
                break

    raise AIServiceError("Groq classification failed (" + "; ".join(failures) + ").")


