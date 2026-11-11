"""Cloudflare Free-plan entry point for the ResQLink demo.

This intentionally exposes the mobile app's live demo flow without relying on a
local SQLite file or a long-running ASGI server. Persisted facilities and live
SACHET collection are not part of this stateless first Cloudflare demo.
"""
import hashlib
import json
import os
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.services.emergency_service import (
    EMERGENCY_CONTACT_INDIA,
    FACILITY_SUGGESTIONS,
    GUIDANCE,
    build_emergency_response,
)
from app.services.weather_service import WeatherServiceError, get_weather_snapshot
from app.services.facility_discovery_service import discover_facilities
from app.services.traffic_service import (
    TrafficNotConfigured,
    TrafficServiceError,
    get_traffic_route,
)


app = FastAPI(
    title="ResQLink Emergency Response API",
    description="Cloudflare Free-plan demo API for multilingual emergency assistance.",
    version="0.5.0-cloudflare-demo",
)


class EmergencyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    language: Literal["en", "hi", "kn"] = "en"
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=10, gt=0, le=200)
    include_weather: bool = False
    weather_forecast_hours: int = Field(default=6, ge=1, le=24)
    use_ai: bool = True

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value):
        if not value.strip():
            raise ValueError("Emergency message cannot be blank.")
        return value.strip()


class TrafficRouteRequest(BaseModel):
    origin_latitude: float = Field(ge=-90, le=90)
    origin_longitude: float = Field(ge=-180, le=180)
    destination_latitude: float = Field(ge=-90, le=90)
    destination_longitude: float = Field(ge=-180, le=180)


def _env(request: Request, name: str, default: str = "") -> str:
    # Production secrets come from the Worker env binding. In local development,
    # Wrangler can also expose values imported from the existing backend/.env.
    env = request.scope.get("env")
    value = getattr(env, name, None) if env is not None else None
    if value is None:
        value = os.getenv(name, default)
    return str(value if value is not None else default)


def _groq_prompt(message: str, language: str, local_type: str) -> str:
    allowed = sorted(FACILITY_SUGGESTIONS)
    allowed_types = sorted(set(
        item
        for values in FACILITY_SUGGESTIONS.values()
        for item in values
    ) | {"unknown"})
    return (
        "Classify this emergency report for ResQLink in India. Return one JSON object only "
        "with emergency_type, confidence, short_summary, and key_details. "
        f"emergency_type must be one of {allowed_types}. "
        "confidence must be high, medium, or low. Keep short_summary under 240 characters. "
        "key_details must be an array of up to five short factual items. "
        "Do not provide safety instructions, medical diagnoses, reassurance, or safe-location claims. "
        "Do not invent places, people, injuries, causes, or coordinates. "
        f"Write summary and key details in language code {language}. "
        f"Local keyword detector hint: {local_type}. If vague, use unknown and low confidence. "
        f"Emergency report: {message}"
    )


def _parse_groq_result(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Groq response was not a JSON object.")

    allowed = {
        "fire", "flood", "earthquake", "cyclone", "landslide", "tsunami",
        "lightning", "gas_leak", "medical", "road_accident", "violence", "unknown",
    }
    kind = str(data.get("emergency_type", "unknown")).strip().lower()
    if kind not in allowed:
        kind = "unknown"
    confidence = str(data.get("confidence", "low")).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    details = data.get("key_details", [])
    if not isinstance(details, list):
        details = []
    return {
        "emergency_type": kind,
        "confidence": confidence,
        "short_summary": str(data.get("short_summary", "")).strip()[:240],
        "key_details": [str(item).strip()[:100] for item in details[:5] if str(item).strip()],
    }


async def _classify_with_groq(
    message: str,
    language: str,
    local_type: str,
    api_key: str,
    primary: str,
    fallback: str,
) -> dict:
    models = list(dict.fromkeys(item for item in (primary, fallback) if item))
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    failures = []
    timeout = httpx.Timeout(13.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for index, model in enumerate(models):
            try:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a careful emergency-report classifier. Never invent facts. Return JSON only.",
                            },
                            {
                                "role": "user",
                                "content": _groq_prompt(message, language, local_type),
                            },
                        ],
                        "response_format": {"type": "json_object"},
                        "max_tokens": 300,
                    },
                )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                return {
                    "status": "connected",
                    "provider": "Groq API",
                    "model": model,
                    **_parse_groq_result(content),
                }
            except Exception as exc:
                failures.append(f"{model}: {type(exc).__name__}")
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = (
                    isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))
                    or status_code in {404, 429, 500, 502, 503, 504}
                )
                if not retryable or index + 1 >= len(models):
                    break
    raise RuntimeError("Groq classification failed (" + "; ".join(failures) + ").")


@app.get("/")
async def home():
    return {
        "message": "ResQLink Emergency Response API is running on Cloudflare Workers Free",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "deployment": "cloudflare-python-worker-free-demo",
        "storage": "stateless-demo",
        "api_version": app.version,
    }


@app.get("/system/status")
async def system_status(request: Request):
    key_configured = bool(_env(request, "GROQ_API_KEY").strip())
    routing_key_configured = bool(_env(request, "OPENROUTESERVICE_API_KEY").strip())
    return {
        "api": {"status": "ok", "version": app.version},
        "database": {
            "status": "stateless_demo",
            "stored_alerts": 0,
            "stored_facilities": 0,
        },
        "providers": {
            "sachet": {
                "configured": True,
                "background_sync_enabled": False,
                "note": "Live SACHET storage/refresh is not enabled in this free demo build.",
            },
            "weather": {
                "provider": "Open-Meteo",
                "request_mode": "on-demand",
                "api_key_required": False,
            },
            "facility_discovery": {
                "provider": "OpenStreetMap Overpass API",
                "api_key_required": False,
                "results_are_unverified": True,
            },
            "ai": {
                "provider": "Groq",
                "enabled": _env(request, "AI_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
                "api_key_configured": key_configured,
                "primary_model": _env(request, "GROQ_MODEL", "qwen/qwen3.8-27b"),
                "fallback_model": _env(request, "GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b"),
                "integration": "async_chat_completions_json_mode",
                "note": "Optional Groq classification; local multilingual keyword detection and curated guidance remain available if AI is not configured.",
            },
            "routing": {
                "provider": "OpenRouteService (HeiGIT)",
                "enabled": routing_key_configured,
                "api_key_configured": routing_key_configured,
                "endpoint": "POST /routes/traffic",
                "travel_mode": "driving-car",
                "live_traffic_available": False,
                "note": (
                    "Road-network route, distance and estimated journey time. "
                    "Live traffic congestion is not included."
                ),
            },
        },
        "mobile": {
            "native_app": "expo_react_native",
            "foreground_gps_permission": "implemented",
            "emergency_submission": "implemented",
            "on_device_offline_cache": "sqlite_cache_implemented",
            "offline_safety_guidance": "implemented",
            "offline_map_tiles": "not_implemented",
            "push_notifications": "not_implemented",
        },
    }


@app.post("/emergency")
async def receive_emergency(payload: EmergencyRequest, request: Request):
    if (payload.latitude is None) != (payload.longitude is None):
        raise HTTPException(
            status_code=422,
            detail="Send both latitude and longitude, or send neither.",
        )

    result = build_emergency_response(payload.message, payload.language)
    ai_enabled = _env(request, "AI_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    api_key = _env(request, "GROQ_API_KEY").strip()
    ai_analysis = {"status": "disabled"}
    ai_requested = payload.use_ai

    if ai_requested and ai_enabled:
        if not api_key:
            ai_analysis = {
                "status": "not_configured",
                "provider": "Groq API",
                "message": "GROQ_API_KEY is not configured on the Cloudflare Worker.",
            }
        else:
            try:
                ai_analysis = await _classify_with_groq(
                    payload.message,
                    payload.language,
                    result.get("emergency_type", "unknown"),
                    api_key,
                    _env(request, "GROQ_MODEL", "qwen/qwen3.8-27b"),
                    _env(request, "GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b"),
                )
                ai_type = ai_analysis.get("emergency_type", "unknown")
                if result.get("emergency_type") == "unknown" and ai_type != "unknown":
                    result["emergency_type"] = ai_type
                    result["all_detected_types"] = [ai_type]
                    result["matched_keywords"] = []
                    result["confidence_label"] = "ai_classification"
                    result["method"] = "groq_classification_with_curated_guidance"
                    result["urgency"] = "urgent"
                    result["guidance"] = GUIDANCE[payload.language][ai_type]
                    result["guidance_by_emergency_type"] = {
                        ai_type: GUIDANCE[payload.language][ai_type]
                    }
                    result["recommended_facility_types"] = FACILITY_SUGGESTIONS[ai_type]
            except Exception as exc:
                ai_analysis = {
                    "status": "unavailable",
                    "provider": "Groq API",
                    "message": str(exc)[:240],
                }

    weather_context = {
        "status": "not_requested",
        "message": "Weather context was not requested.",
    }
    if payload.include_weather and payload.latitude is not None:
        try:
            weather_context = {
                "status": "available",
                **await get_weather_snapshot(
                    payload.latitude,
                    payload.longitude,
                    payload.weather_forecast_hours,
                ),
            }
        except (WeatherServiceError, ValueError) as exc:
            weather_context = {"status": "unavailable", "message": str(exc)[:200]}

    ai_status = ai_analysis.get("status", "unknown")
    return {
        "status": "processed",
        "message": payload.message,
        **result,
        "analysis_engine": (
            "groq_classification_with_curated_guidance"
            if ai_status == "connected"
            else "local_multilingual_nlp_fallback"
        ),
        "ai_provider": "Groq",
        "ai_status": ai_status,
        "ai_analysis": ai_analysis,
        "location_used": (
            {
                "latitude": payload.latitude,
                "longitude": payload.longitude,
                "radius_km": payload.radius_km,
            }
            if payload.latitude is not None else None
        ),
        "nearby_facilities": [],
        "nearby_alerts": [],
        "unverified_alerts": [],
        "weather_context": weather_context,
        "data_limitations": [
            "This Cloudflare Free demo build does not persist server-side facilities, saved locations or SACHET alerts.",
            "Nearby facility discovery returns unverified OpenStreetMap candidates only.",
            "Weather output is forecast context, not an official warning or guarantee of local conditions.",
        ],
    }


def _make_etag(package: dict) -> str:
    stable = {key: value for key, value in package.items() if key != "generated_at"}
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return '"' + hashlib.sha256(raw.encode("utf-8")).hexdigest() + '"'


@app.get("/offline/package")
async def offline_package(
    response: Response,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    language: Literal["en", "hi", "kn"] = "en",
    radius_km: float = Query(default=10, gt=0, le=100),
    city: Optional[str] = Query(default=None, max_length=120),
    district: Optional[str] = Query(default=None, max_length=120),
    state: Optional[str] = Query(default=None, max_length=120),
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
):
    package = {
        "package_type": "resqlink_offline_emergency_package",
        "schema_version": 1,
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "language": language,
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "city": city,
            "district": district,
            "state": state,
            "radius_km": radius_km,
        },
        "emergency_contact": EMERGENCY_CONTACT_INDIA,
        "guidance_catalog": {
            category: {
                "instructions": instructions,
                "recommended_facility_types": FACILITY_SUGGESTIONS.get(category, []),
            }
            for category, instructions in GUIDANCE[language].items()
        },
        "nearby_verified_facilities": [],
        "location_matched_official_alerts": [],
        "unverified_location_alerts": [],
        "offline_capabilities": {
            "multilingual_safety_guides": True,
            "emergency_contact_number": True,
            "verified_facility_directory": False,
            "downloaded_official_alert_snapshot": False,
            "map_tiles_included": False,
            "live_alert_updates": False,
            "live_weather_updates": False,
            "live_traffic_updates": False,
        },
        "refresh_recommended_after_seconds": 900,
        "important": [
            "This demo package contains curated safety guides and the India emergency number 112.",
            "Server-side facility records and official SACHET alerts are not included in this free demo build.",
            "Map tiles, live routing, weather and traffic are not bundled.",
            "Never treat absence of an alert or facility as proof that an area is safe.",
        ],
    }

    etag = _make_etag(package)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["X-Package-Checked-At"] = package["generated_at"]
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers=dict(response.headers))
    return package


@app.get("/weather/nearby")
async def nearby_weather(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    forecast_hours: int = Query(default=12, ge=1, le=24),
):
    try:
        return await get_weather_snapshot(latitude, longitude, forecast_hours)
    except (WeatherServiceError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:200]) from exc


@app.post("/routes/traffic")
async def traffic_route(payload: TrafficRouteRequest, request: Request):
    api_key = _env(request, "OPENROUTESERVICE_API_KEY").strip()
    try:
        return await get_traffic_route(
            payload.origin_latitude,
            payload.origin_longitude,
            payload.destination_latitude,
            payload.destination_longitude,
            api_key=api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TrafficNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TrafficServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/facilities/discover")
async def discover_nearby_facilities(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=5, ge=1, le=20),
):
    try:
        return await discover_facilities(latitude, longitude, radius_km)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:200]) from exc


@app.get("/alerts")
async def list_alerts(active_only: bool = True, limit: int = Query(default=100, ge=1, le=500)):
    return {
        "count": 0,
        "items": [],
        "source_note": "SACHET alert ingestion and persistence are not enabled in this stateless free demo build.",
    }


@app.get("/alerts/nearby")
async def nearby_alerts(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
):
    return {
        "count": 0,
        "items": [],
        "location_used": {"latitude": latitude, "longitude": longitude},
        "important": "No alert data is stored by this demo build. Check official NDMA SACHET channels.",
    }


@app.get("/alerts/sync-status")
async def alert_sync_status():
    return {
        "background_sync_enabled": False,
        "state": {
            "status": "disabled_in_stateless_free_demo",
            "message": "The long-running alert collector has not been ported to a scheduled Cloudflare job yet.",
        },
    }


from workers import WorkerEntrypoint


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        import asgi
        return await asgi.fetch(app, request.js_object, self.env)
