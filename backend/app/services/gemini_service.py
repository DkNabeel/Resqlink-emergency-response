"""Short-timeout Gemini intent classification for ResQLink."""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

ALLOWED_TYPES = {
    "fire", "flood", "earthquake", "cyclone", "landslide", "tsunami",
    "lightning", "gas_leak", "medical", "road_accident", "violence", "unknown",
}


class GeminiServiceError(RuntimeError):
    """Gemini unavailable or returned an invalid classification."""


def parse_classification(text):
    if not isinstance(text, str) or not text.strip():
        raise GeminiServiceError("Gemini returned an empty response.")
    cleaned = text.strip()
    cleaned = re.sub(r"^\s*\x60\x60\x60(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*\x60\x60\x60\s*$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise GeminiServiceError("Gemini did not return valid JSON.")
        try:
            payload = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise GeminiServiceError("Gemini did not return valid JSON.") from exc

    if not isinstance(payload, dict):
        raise GeminiServiceError("Gemini response must be a JSON object.")
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
        "key_details": [str(x).strip()[:100] for x in details[:5] if str(x).strip()],
    }


def _prompt(message, language, local_type):
    return (
        "Classify this emergency report for ResQLink in India. Return JSON only with "
        "emergency_type, confidence, short_summary, and key_details. "
        f"emergency_type must be one of {sorted(ALLOWED_TYPES)}. "
        "confidence must be high, medium, or low. summary max 240 characters; "
        "key_details is up to five short factual items. "
        "Do not write safety instructions, medical diagnoses, reassurance, or safe-location claims. "
        "Do not invent places, people, injuries, causes, or coordinates. "
        f"Requested response language: {language}. "
        f"Local keyword detector hint: {local_type}. "
        "If vague, choose unknown with low confidence.\nUser report:\n"
        + message.strip()
    )


def analyze_emergency_with_gemini(message, language="en", local_type="unknown"):
    """Use generateContent once; fallback model only when the primary is unavailable."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string.")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiServiceError("GEMINI_API_KEY is not configured.")

    primary = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    fallback = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite").strip()
    # Gemini 3.8 requires a manually configured request deadline of at least 10 seconds.
    # Clamp local .env overrides upward so a stale 5s/9s value cannot cause HTTP 400.
    timeout_ms = max(10000, min(15000, int(os.getenv("GEMINI_HTTP_TIMEOUT_MS", "10000"))))
    models = list(dict.fromkeys(model for model in (primary, fallback) if model))
    client = genai.Client(
        api_key=api_key,
        http_options={"timeout": timeout_ms, "retry_options": {"attempts": 0}},
    )
    failures = []
    try:
        for index, model in enumerate(models):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=_prompt(message, language, local_type),
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        max_output_tokens=300,
                    ),
                )
                parsed = parse_classification(getattr(response, "text", None))
                return {
                    "status": "connected",
                    "provider": "Google Gemini API",
                    "model": model,
                    **parsed,
                }
            except GeminiServiceError:
                raise
            except Exception as exc:
                status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                raw_detail = getattr(exc, "message", None) or str(exc)
                safe_detail = str(raw_detail).replace(api_key, "[REDACTED]")[:400]
                status_label = f"HTTP {status_code}" if status_code else type(exc).__name__
                failures.append(f"{model}: {status_label}: {safe_detail}")
                detail = str(raw_detail).lower()
                error_name = type(exc).__name__.lower()
                model_missing = (
                    "404" in detail or "not found" in detail or "unknown model" in detail
                )
                transient_upstream = (
                    any(code in detail for code in ("500", "502", "503", "504"))
                    or "deadline_exceeded" in detail
                    or "deadline exceeded" in detail
                    or "deadline expired" in detail
                    or "deadline has expired" in detail
                    or "timed out" in detail
                    or "timeout" in detail
                    or error_name in {"readtimeout", "connecttimeout", "timeoutexception"}
                )
                # Do not retry quota/auth failures (usually 401/403/429). A
                # single fallback is useful for model availability and 5xx/
                # deadline failures such as the previous 504 issue.
                if not ((model_missing or transient_upstream) and index + 1 < len(models)):
                    break
    finally:
        try:
            client.close()
        except Exception:
            pass

    raise GeminiServiceError(
        "Gemini generation failed (" + "; ".join(failures) + "). "
        "Check AI Studio key access, model availability, quota and network."
    )


def generate_reply(message):
    """Backward-compatible helper for the older one-line test script."""
    result = analyze_emergency_with_gemini(message)
    return result.get("short_summary") or result["emergency_type"]
