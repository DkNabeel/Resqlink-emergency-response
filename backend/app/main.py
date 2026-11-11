import asyncio
import hashlib
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

# Load backend/.env here as well as in individual services. FastAPI does not
# automatically load a .env file unless the server is started with --env-file.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.database.alert_repository import (
    get_active_alerts,
    get_alert_count,
    get_feed_state,
    get_recent_alerts,
)
from app.database.facility_repository import (
    create_facility,
    delete_facility,
    get_all_facilities,
    set_facility_verification,
    update_facility,
)
from app.database.init_db import create_tables
from app.database.location_repository import get_last_location, save_location
from app.services.emergency_service import (
    EMERGENCY_CONTACT_INDIA,
    FACILITY_SUGGESTIONS,
    GUIDANCE,
    build_emergency_response,
)
from app.services.geospatial_service import haversine_km, match_alert_location
from app.services.ai_service import AIServiceError, analyze_emergency_with_groq, respond_to_emergency_chat
from app.services.traffic_service import TrafficNotConfigured, TrafficServiceError, get_traffic_route
from app.services.facility_discovery_service import discover_facilities
from app.services.location_service import estimate_location_from_ip
from app.services.sachet_service import DEFAULT_SACHET_FEED, sync_sachet_feed
from app.services.weather_service import WeatherServiceError, get_weather_snapshot


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("resqlink")

SACHET_FEED_URL = os.getenv("SACHET_FEED_URL", DEFAULT_SACHET_FEED)


async def _alert_refresh_loop():
    interval = max(60, int(os.getenv("SACHET_REFRESH_SECONDS", "300")))
    while True:
        try:
            result = await sync_sachet_feed(SACHET_FEED_URL)
            logger.info(
                "SACHET sync finished: status=%s, rss_items=%s, cap_enriched=%s, polygon_alerts=%s",
                result["status"],
                result.get("new_alerts", 0),
                result.get("enriched_alerts", 0),
                result.get("polygon_alerts", 0),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("SACHET sync failed: %s", exc)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    sync_enabled = os.getenv("SACHET_SYNC_ENABLED", "true").strip().lower()
    task = None
    if sync_enabled in {"1", "true", "yes", "on"}:
        task = asyncio.create_task(_alert_refresh_loop())
        logger.info("Background SACHET alert collector started.")
    else:
        logger.info("Background SACHET alert collector is disabled.")
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="ResQLink Emergency Response API",
    description=(
        "Backend API for multilingual emergency assistance, official alert "
        "collection, location resilience and nearby facility information."
    ),
    version="0.4.0",
    lifespan=lifespan,
)


class EmergencyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    use_gemini: bool = True  # Deprecated alias retained for older mobile clients.
    use_ai: Optional[bool] = None
    language: Literal["en", "hi", "kn"] = "en"

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value):
        if not value.strip():
            raise ValueError("Emergency message cannot be blank.")
        return value.strip()
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=10, gt=0, le=200)
    city: Optional[str] = Field(default=None, max_length=120)
    district: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=120)
    include_weather: bool = False
    weather_forecast_hours: int = Field(default=6, ge=1, le=24)


class EmergencyChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1600)


class EmergencyChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language: Literal["en", "hi", "kn"] = "en"
    conversation_history: list[EmergencyChatHistoryMessage] = Field(default_factory=list, max_length=10)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=10, gt=0, le=20)
    city: Optional[str] = Field(default=None, max_length=120)
    district: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=120)

    @field_validator("message")
    @classmethod
    def chat_message_must_not_be_blank(cls, value):
        if not value.strip():
            raise ValueError("Emergency message cannot be blank.")
        return value.strip()


class TrafficRouteRequest(BaseModel):
    origin_latitude: float = Field(ge=-90, le=90)
    origin_longitude: float = Field(ge=-180, le=180)
    destination_latitude: float = Field(ge=-90, le=90)
    destination_longitude: float = Field(ge=-180, le=180)


class FacilityRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    facility_type: Literal["hospital", "police", "fire_station", "ambulance", "shelter", "other"]

    @field_validator("name")
    @classmethod
    def facility_name_must_not_be_blank(cls, value):
        if not value.strip():
            raise ValueError("Facility name cannot be blank.")
        return value.strip()
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: Optional[str] = Field(default=None, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=40)
    source_name: Optional[str] = Field(default=None, max_length=200)


class FacilityVerificationRequest(BaseModel):
    verification_status: Literal["verified", "unverified"]
    verification_note: str = Field(min_length=8, max_length=500)

    @field_validator("verification_note")
    @classmethod
    def verification_note_must_not_be_blank(cls, value):
        if len(value.strip()) < 8:
            raise ValueError("Verification note must contain at least 8 non-space characters.")
        return value.strip()


class LocationResolveRequest(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    accuracy_m: Optional[float] = Field(default=None, ge=0, le=1000000)
    source: Literal["gps", "manual"] = "gps"
    city: Optional[str] = Field(default=None, max_length=120)
    district: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=120)
    country: Optional[str] = Field(default=None, max_length=120)


def _location_age_minutes(recorded_at):
    try:
        value = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - value).total_seconds() / 60))
    except (TypeError, ValueError, AttributeError):
        return None


def _format_saved_location(record, *, current=False, message=None):
    return {
        "location_available": True,
        "location_is_current": current,
        "is_approximate": record["source"] == "ip",
        **record,
        "age_minutes": _location_age_minutes(record.get("recorded_at")),
        "message": message,
    }


@app.get("/")
def home():
    return {
        "message": "ResQLink Emergency Response API is running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "database": "connected",
        "stored_alerts": get_alert_count(),
        "stored_facilities": len(get_all_facilities()),
        "api_version": app.version,
    }


@app.get("/system/status")
def system_status():
    feed_state = get_feed_state(SACHET_FEED_URL)
    return {
        "api": {"status": "ok", "version": app.version},
        "database": {
            "status": "connected",
            "stored_alerts": get_alert_count(),
            "stored_facilities": len(get_all_facilities()),
        },
        "providers": {
            "sachet": {
                "configured": bool(SACHET_FEED_URL),
                "background_sync_enabled": os.getenv("SACHET_SYNC_ENABLED", "true").lower()
                    in {"1", "true", "yes", "on"},
                "last_sync": feed_state,
            },
            "weather": {
                "provider": "Open-Meteo",
                "request_mode": "on-demand",
                "api_key_required": False,
            },
            "traffic": {
                "provider": "OpenRouteService (HeiGIT)",
                "api_key_configured": bool(os.getenv("OPENROUTESERVICE_API_KEY")),
                "live_traffic_available": False,
                "route_estimates": "road_network_based",
            },
            "facility_discovery": {
                "provider": "OpenStreetMap Overpass API",
                "api_key_required": False,
                "results_are_unverified": True,
            },
            "ai": {
                "provider": "Groq",
                "enabled": os.getenv("AI_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
                "api_key_configured": bool(os.getenv("GROQ_API_KEY")),
                "primary_model": os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
                "fallback_model": os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b"),
                "integration": "chat_completions_json_mode",
                "billing_mode": "free_tier_rate_limited",
                "note": "Groq powers dynamic emergency-only chat at /emergency/chat; the original /emergency classification endpoint remains available for compatibility.",
            },
        },
        "mobile": {
            "native_app": "expo_react_native_source_added",
            "foreground_gps_permission": "required_by_app",
            "notification_permission": "required_by_app",
            "dynamic_emergency_only_groq_chat": "implemented_source_requires_live_test",
            "online_map_and_facility_routes": "implemented_source_requires_device_test",
            "weather_popup": "implemented_source_requires_device_test",
            "nearby_facility_offline_package": "included_when_openstreetmap_discovery_succeeds",
            "on_device_offline_cache": "sqlite_latest_package_cache",
            "offline_safety_guidance": "multilingual_keyword_fallback",
            "background_location_refresh": "best_effort_requires_background_permission_and_native_build",
            "local_sachet_alert_notifications": "best_effort_requires_background_location_and_matched_alerts",
            "remote_push_notifications": "not_implemented",
            "offline_map_tiles_and_road_routing": "not_implemented",
            "note": "Source implementation is present; background cadence is OS-controlled and all features still require native-device validation.",
        },
    }


@app.post("/emergency/chat")
async def emergency_chat(request: EmergencyChatRequest):
    """Dynamic, emergency-only Groq conversation with official/local context."""
    if (request.latitude is None) != (request.longitude is None):
        raise HTTPException(status_code=422, detail="Send both latitude and longitude, or neither.")

    history = [
        {"role": item.role, "content": item.content}
        for item in request.conversation_history
    ]
    context_text = "\n".join(
        [item["content"] for item in history[-8:]] + [request.message]
    )
    local_result = build_emergency_response(context_text, request.language)
    local_type = local_result.get("emergency_type", "unknown")
    trusted_guidance = GUIDANCE[request.language].get(
        local_type, GUIDANCE[request.language]["unknown"]
    )

    confirmed_alerts = []
    unverified_alerts = []
    nearby_facilities = []
    weather_context = None
    has_location = request.latitude is not None and request.longitude is not None

    if has_location:
        for alert in get_active_alerts(200):
            match = match_alert_location(
                alert, request.latitude, request.longitude,
                city=request.city, district=request.district, state=request.state,
            )
            if match["matched"] is True:
                confirmed_alerts.append({
                    "title": alert.get("title"),
                    "event": alert.get("event"),
                    "severity": alert.get("severity"),
                    "description": alert.get("description"),
                    "area_description": alert.get("area_description"),
                    "expires_at": alert.get("expires_at"),
                    "source_url": alert.get("source_url"),
                    "location_match": match,
                    "source": "SACHET",
                })
            elif match["matched"] is None:
                unverified_alerts.append({
                    "title": alert.get("title"),
                    "event": alert.get("event"),
                    "severity": alert.get("severity"),
                    "area_description": alert.get("area_description"),
                    "expires_at": alert.get("expires_at"),
                    "source_url": alert.get("source_url"),
                    "location_match": match,
                    "source": "SACHET",
                    "warning": "Location relevance is unverified.",
                })

        suggested_types = set(local_result.get("recommended_facility_types", []))
        for facility in get_all_facilities(verification_status="verified", limit=1000):
            distance = haversine_km(
                request.latitude, request.longitude,
                float(facility["latitude"]), float(facility["longitude"]),
            )
            if distance <= request.radius_km and (
                not suggested_types or facility["facility_type"] in suggested_types
            ):
                nearby_facilities.append({
                    **facility, "distance_km": round(distance, 2),
                    "verification_status": "verified",
                })

    ai_analysis = {"status": "disabled"}
    ai_enabled = os.getenv("AI_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    if ai_enabled and os.getenv("GROQ_API_KEY", "").strip():
        timeout_seconds = max(20, min(32, int(os.getenv("AI_TOTAL_TIMEOUT_SECONDS", "30"))))
        try:
            ai_analysis = await asyncio.wait_for(
                asyncio.to_thread(
                    respond_to_emergency_chat,
                    request.message,
                    request.language,
                    history,
                    local_type,
                    trusted_guidance,
                    confirmed_alerts,
                    weather_context,
                    nearby_facilities,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            ai_analysis = {"status": "timeout", "message": "Groq emergency chat timed out."}
        except AIServiceError as exc:
            logger.warning("Groq emergency chat unavailable: %s", exc)
            ai_analysis = {"status": "unavailable", "message": str(exc)[:240]}
        except Exception as exc:
            logger.exception("Unexpected Groq emergency-chat failure")
            ai_analysis = {"status": "error", "message": type(exc).__name__}

    if ai_analysis.get("status") == "connected":
        in_scope = bool(ai_analysis.get("in_scope"))
        reply = ai_analysis.get("reply", "")
        emergency_type = ai_analysis.get("emergency_type", local_type)
        urgency = ai_analysis.get("urgency", "unknown")
        follow_up = ai_analysis.get("follow_up_question")
    else:
        in_scope = local_type != "unknown"
        emergency_type = local_type
        urgency = local_result.get("urgency", "unknown")
        reply = (
            "I can help with this emergency, but the AI service is unavailable. "
            + " ".join(trusted_guidance)
            if in_scope else
            "I can only help with emergency situations. Please describe the danger you are facing."
        )
        follow_up = None

    if not in_scope:
        return {
            "status": "processed",
            "in_scope": False,
            "reply": reply,
            "follow_up_question": follow_up,
            "ai_provider": "Groq",
            "ai_status": ai_analysis.get("status", "unknown"),
            "ai_analysis": ai_analysis,
            "emergency_contact": EMERGENCY_CONTACT_INDIA,
        }

    return {
        "status": "processed",
        "in_scope": True,
        "reply": reply,
        "follow_up_question": follow_up,
        "emergency_type": emergency_type,
        "urgency": urgency,
        "ai_provider": "Groq",
        "ai_status": ai_analysis.get("status", "unknown"),
        "ai_analysis": ai_analysis,
        "local_nlp_type": local_type,
        "emergency_contact": EMERGENCY_CONTACT_INDIA,
        "nearby_facilities": nearby_facilities,
        "nearby_alerts": confirmed_alerts,
        "unverified_alerts": unverified_alerts,
        "location_used": (
            {"latitude": request.latitude, "longitude": request.longitude, "radius_km": request.radius_km}
            if has_location else None
        ),
        "weather_context": weather_context,
        "data_limitations": [
            "Unverified OpenStreetMap candidates must be checked before relying on them.",
            "A road-network route estimate is not a hazard-safe-route guarantee.",
            "Only positively matched SACHET alerts are treated as confirmed local alerts.",
        ],
    }


@app.post("/emergency")
async def receive_emergency(request: EmergencyRequest):
    has_latitude = request.latitude is not None
    has_longitude = request.longitude is not None
    if has_latitude != has_longitude:
        raise HTTPException(
            status_code=422,
            detail="Send both latitude and longitude, or send neither.",
        )

    result = build_emergency_response(request.message.strip(), request.language)
    ai_analysis = {"status": "disabled"}
    ai_enabled = os.getenv("AI_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    ai_requested = request.use_gemini if request.use_ai is None else request.use_ai

    if ai_requested and ai_enabled:
        if os.getenv("GROQ_API_KEY", "").strip():
            # Two bounded provider attempts (primary + fallback) fit inside this limit.
            timeout_seconds = max(20, min(32, int(os.getenv("AI_TOTAL_TIMEOUT_SECONDS", "30"))))
            try:
                ai_analysis = await asyncio.wait_for(
                    asyncio.to_thread(
                        analyze_emergency_with_groq,
                        request.message.strip(),
                        request.language,
                        result.get("emergency_type", "unknown"),
                    ),
                    timeout=timeout_seconds,
                )
                ai_type = ai_analysis.get("emergency_type", "unknown")
                # Local keyword matches remain primary. Groq may fill unknown
                # classifications, while safety instructions remain curated.
                if result.get("emergency_type") == "unknown" and ai_type != "unknown":
                    result["emergency_type"] = ai_type
                    result["all_detected_types"] = [ai_type]
                    result["matched_keywords"] = []
                    result["confidence_label"] = "ai_classification"
                    result["method"] = "groq_classification_with_curated_guidance"
                    result["urgency"] = "urgent"
                    result["guidance"] = GUIDANCE[request.language][ai_type]
                    result["guidance_by_emergency_type"] = {ai_type: GUIDANCE[request.language][ai_type]}
                    result["recommended_facility_types"] = FACILITY_SUGGESTIONS[ai_type]
            except asyncio.TimeoutError:
                ai_analysis = {
                    "status": "timeout",
                    "message": "Groq exceeded the response time limit; local emergency analysis was used.",
                }
            except AIServiceError as exc:
                logger.warning("Groq classification unavailable: %s", exc)
                ai_analysis = {"status": "unavailable", "message": str(exc)[:280]}
            except Exception as exc:
                logger.exception("Unexpected Groq classification failure")
                ai_analysis = {"status": "error", "message": f"Unexpected AI error: {type(exc).__name__}"}
        else:
            ai_analysis = {
                "status": "not_configured",
                "message": "Set GROQ_API_KEY in backend/.env to enable Groq AI classification.",
            }
    elif not ai_enabled:
        ai_analysis = {"status": "disabled_by_server"}
    nearby_facilities = []
    nearby_alerts = []
    unverified_alerts = []
    weather_context = {
        "status": "not_requested",
        "message": "Provide coordinates and set include_weather=true to request forecast context.",
    }

    if has_latitude and has_longitude:
        suggested_types = set(result.get("recommended_facility_types", []))
        # Emergency results must never promote unverified facility records.
        for facility in get_all_facilities(verification_status="verified"):
            if facility["facility_type"] not in suggested_types:
                continue
            distance = haversine_km(
                request.latitude,
                request.longitude,
                float(facility["latitude"]),
                float(facility["longitude"]),
            )
            if distance <= request.radius_km:
                nearby_facilities.append({**facility, "distance_km": round(distance, 2)})
        nearby_facilities.sort(key=lambda item: item["distance_km"])

        for alert in get_active_alerts(200):
            match = match_alert_location(
                alert, request.latitude, request.longitude,
                city=request.city, district=request.district, state=request.state,
            )
            if match["matched"] is True:
                nearby_alerts.append({**alert, "location_match": match})
            elif match["matched"] is None:
                unverified_alerts.append({
                    "alert_id": alert["alert_id"],
                    "title": alert["title"],
                    "area_description": alert.get("area_description"),
                    "location_match": match,
                    "warning": "Location relation is unverified; inspect the original official alert.",
                })

        if request.include_weather:
            try:
                weather_data = await get_weather_snapshot(
                    request.latitude,
                    request.longitude,
                    request.weather_forecast_hours,
                )
                weather_context = {
                    "status": weather_data.get("cache_status", "available"),
                    "data": weather_data,
                    "note": "Forecast context only; not an official warning or a substitute for government alerts.",
                }
            except (WeatherServiceError, ValueError) as exc:
                logger.warning("Emergency weather context unavailable: %s", exc)
                weather_context = {
                    "status": "unavailable",
                    "message": "Weather provider is currently unavailable. Continue using official alerts and local responder instructions.",
                }
    elif request.include_weather:
        weather_context = {
            "status": "not_requested",
            "message": "Weather context requires both latitude and longitude.",
        }

    return {
        "status": "processed",
        "message": request.message.strip(),
        **result,
        "analysis_engine": (
            "groq_classification_with_curated_guidance"
            if ai_analysis.get("status") == "connected"
            else "local_multilingual_nlp_fallback"
        ),
        "ai_provider": "Groq",
        "ai_status": ai_analysis.get("status", "unknown"),
        "ai_analysis": ai_analysis,
        # Backward-compatible response aliases for older app builds.
        "gemini_status": ai_analysis.get("status", "unknown"),
        "gemini_analysis": ai_analysis,
        "location_used": (
            {"latitude": request.latitude, "longitude": request.longitude, "radius_km": request.radius_km}
            if has_latitude else None
        ),
        "nearby_facilities": nearby_facilities,
        "nearby_alerts": nearby_alerts,
        "unverified_alerts": unverified_alerts,
        "weather_context": weather_context,
        "data_limitations": [
            "SACHET polygon endpoint currently returns HTTP 403 in this environment.",
            "District/locality text matching is not polygon-verified.",
            "An empty facility list may mean no facilities have been entered in the database.",
        ],
    }


@app.get("/alerts")
def list_alerts(
    active_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
):
    alerts = get_active_alerts(limit) if active_only else get_recent_alerts(limit)
    return {
        "count": len(alerts),
        "items": alerts,
        "source_note": "Official feed content is shown with its source and timestamps.",
    }


@app.get("/alerts/nearby")
def nearby_alerts(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    city: Optional[str] = None,
    district: Optional[str] = None,
    state: Optional[str] = None,
    include_unverified: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
):
    matched = []
    for alert in get_active_alerts(limit):
        location_match = match_alert_location(
            alert,
            latitude,
            longitude,
            city=city,
            district=district,
            state=state,
        )
        if location_match["matched"] is True:
            matched.append({**alert, "location_match": location_match})
        elif location_match["matched"] is None and include_unverified:
            matched.append({
                **alert,
                "location_match": location_match,
                "relevance_warning": (
                    "The source feed did not provide machine-readable affected-area "
                    "geometry or a confirmed locality match. Review the official alert."
                ),
            })

    return {
        "count": len(matched),
        "items": matched,
        "location_used": {"latitude": latitude, "longitude": longitude},
        "important": (
            "A missing geographic boundary is not proof that an alert is irrelevant. "
            "Unverified items are labelled and must not be treated as confirmed local alerts."
        ),
    }


@app.get("/alerts/sync-status")
def alert_sync_status():
    state = get_feed_state(SACHET_FEED_URL)
    return {
        "feed_url": SACHET_FEED_URL,
        "refresh_interval_seconds": max(
            60, int(os.getenv("SACHET_REFRESH_SECONDS", "300"))
        ),
        "background_sync_enabled": (
            os.getenv("SACHET_SYNC_ENABLED", "true").strip().lower()
            in {"1", "true", "yes", "on"}
        ),
        "state": state,
    }


@app.post("/locations/resolve")
async def resolve_location(payload: LocationResolveRequest, request: Request):
    has_latitude = payload.latitude is not None
    has_longitude = payload.longitude is not None
    if has_latitude != has_longitude:
        raise HTTPException(
            status_code=422,
            detail="Send both latitude and longitude, or send neither.",
        )

    if has_latitude and has_longitude:
        save_location(
            device_id=payload.device_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            source=payload.source,
            accuracy_m=payload.accuracy_m,
            city=payload.city,
            district=payload.district,
            state=payload.state,
            country=payload.country,
        )
        record = {
            "device_id": payload.device_id,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "source": payload.source,
            "accuracy_m": payload.accuracy_m,
            "city": payload.city,
            "district": payload.district,
            "state": payload.state,
            "country": payload.country,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        return _format_saved_location(
            record,
            current=payload.source == "gps",
            message=(
                "Current GPS location received."
                if payload.source == "gps"
                else "Manually selected location saved."
            ),
        )

    # A manually selected place remains the user's explicit choice.
    last_manual = get_last_location(payload.device_id, source="manual")
    if last_manual:
        return _format_saved_location(
            last_manual,
            message="Using the last manually selected location.",
        )

    # Prefer a recent GPS fix over a less accurate IP estimate.
    last_gps = get_last_location(payload.device_id, source="gps")
    gps_age = (
        _location_age_minutes(last_gps.get("recorded_at"))
        if last_gps else None
    )
    if last_gps and gps_age is not None and gps_age <= 60:
        return _format_saved_location(
            last_gps,
            message="GPS is currently unavailable; using a recent saved GPS location.",
        )

    # IP lookup is opt-in and only uses the direct client address. Do not trust
    # X-Forwarded-For unless a trusted-proxy configuration is deliberately added.
    client_ip = request.client.host if request.client else None
    if client_ip:
        estimate = await estimate_location_from_ip(client_ip)
        if estimate:
            return {
                "location_available": True,
                "location_is_current": False,
                **estimate,
            }

    if last_gps:
        return _format_saved_location(
            last_gps,
            message="Using an older saved GPS location. It may no longer be current.",
        )

    last_location = get_last_location(payload.device_id)
    if last_location:
        return _format_saved_location(
            last_location,
            message="Using the last saved location. It may no longer be current.",
        )

    return {
        "location_available": False,
        "location_is_current": False,
        "message": (
            "No current or saved location is available. Enable location services "
            "or let the user select a city/area manually."
        ),
    }


@app.get("/locations/{device_id}/last-known")
def last_known_location(device_id: str):
    record = get_last_location(device_id)
    if not record:
        return {
            "location_available": False,
            "message": "No saved location exists for this device yet.",
        }
    return _format_saved_location(
        record,
        message="Saved location; check its age before using it for location-sensitive guidance.",
    )


def _offline_package_etag(package):
    """Hash stable package content while ignoring generation/check timestamps."""
    stable_payload = {
        key: value for key, value in package.items()
        if key != "generated_at"
    }
    # A collector refresh can update last_seen_at without changing the alert
    # information a mobile client actually needs.
    for group_name in (
        "location_matched_official_alerts",
        "unverified_location_alerts",
    ):
        stable_payload[group_name] = [
            {key: value for key, value in item.items() if key != "last_seen_at"}
            for item in stable_payload.get(group_name, [])
        ]
    canonical = json.dumps(
        stable_payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f'"{digest}"'


def _etag_matches(if_none_match, current_etag):
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        token = candidate.strip()
        if token == "*" or token == current_etag:
            return True
        if token.startswith("W/") and token[2:] == current_etag:
            return True
    return False


@app.get("/offline/package")
async def create_offline_package(
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
    generated_at = datetime.now(timezone.utc).isoformat()

    verified_facilities = get_all_facilities(
        verification_status="verified",
        limit=1000,
    )
    nearby_verified_facilities = []
    for facility in verified_facilities:
        distance = haversine_km(
            latitude,
            longitude,
            float(facility["latitude"]),
            float(facility["longitude"]),
        )
        if distance <= radius_km:
            nearby_verified_facilities.append({
                **facility,
                "distance_km": round(distance, 2),
            })
    nearby_verified_facilities.sort(key=lambda item: item["distance_km"])

    # Include nearby OpenStreetMap candidates in the package so the phone can
    # save them locally. They remain explicitly unverified and are never
    # promoted to verified facilities automatically.
    nearby_discovered_facilities = []
    facility_discovery_status = "unavailable"
    try:
        discovery = await discover_facilities(
            latitude, longitude, min(20, radius_km)
        )
        nearby_discovered_facilities = discovery.get("items", [])
        facility_discovery_status = "available"
    except Exception as exc:
        logger.warning("Facility discovery unavailable for offline package: %s", type(exc).__name__)

    local_alerts = []
    unverified_alerts = []
    for alert in get_active_alerts(200):
        match = match_alert_location(
            alert,
            latitude,
            longitude,
            city=city,
            district=district,
            state=state,
        )
        if match["matched"] is True:
            local_alerts.append({
                **alert,
                "location_match": match,
            })
        elif match["matched"] is None:
            unverified_alerts.append({
                "alert_id": alert["alert_id"],
                "title": alert["title"],
                "event": alert.get("event"),
                "severity": alert.get("severity"),
                "expires_at": alert.get("expires_at"),
                "source_url": alert.get("source_url"),
                "area_description": alert.get("area_description"),
                "location_match": match,
                "warning": "The alert may be relevant, but its geographic relation is unconfirmed.",
            })

    guidance_catalog = {
        category: {
            "instructions": instructions,
            "recommended_facility_types": FACILITY_SUGGESTIONS.get(category, []),
        }
        for category, instructions in GUIDANCE[language].items()
    }

    package = {
        "package_type": "resqlink_offline_emergency_package",
        "schema_version": 1,
        "generated_at": generated_at,
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
        "guidance_catalog": guidance_catalog,
        "nearby_verified_facilities": nearby_verified_facilities,
        "nearby_discovered_facilities": nearby_discovered_facilities,
        "facility_discovery_status": facility_discovery_status,
        "location_matched_official_alerts": local_alerts,
        "unverified_location_alerts": unverified_alerts,
        "offline_capabilities": {
            "multilingual_safety_guides": True,
            "emergency_contact_number": True,
            "verified_facility_directory": True,
            "unverified_osm_facility_candidates": True,
            "downloaded_official_alert_snapshot": True,
            "map_tiles_included": False,
            "live_alert_updates": False,
            "live_weather_updates": False,
            "live_traffic_updates": False,
        },
        "refresh_recommended_after_seconds": 900,
        "important": [
            "This is a snapshot generated at the stated time; new alerts cannot arrive while offline.",
            "Check each alert's own expiry and status; the package has no guaranteed validity period.",
            "Verified facilities and separately labelled unverified OpenStreetMap candidates are included. Check candidate details before relying on them.",
            "Map tiles, live routing, weather and traffic are not bundled.",
            "Never treat absence of an alert or facility as proof that an area is safe.",
        ],
    }

    etag = _offline_package_etag(package)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["X-Package-Checked-At"] = generated_at

    # Allow a mobile client to avoid downloading an unchanged package over a
    # weak connection. Generation timestamps are deliberately excluded from
    # the content hash so identical data can return 304 Not Modified.
    if _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=dict(response.headers))

    return package


@app.post("/routes/traffic")
async def traffic_route(payload: TrafficRouteRequest):
    try:
        return await get_traffic_route(
            payload.origin_latitude,
            payload.origin_longitude,
            payload.destination_latitude,
            payload.destination_longitude,
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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/weather/nearby")
async def nearby_weather(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    forecast_hours: int = Query(default=12, ge=1, le=24),
):
    try:
        return await get_weather_snapshot(latitude, longitude, forecast_hours)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WeatherServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/facilities")
def list_facilities(
    facility_type: Optional[str] = None,
    verification_status: Optional[Literal["verified", "unverified"]] = None,
    limit: int = Query(default=500, ge=1, le=1000),
):
    items = get_all_facilities(
        verification_status=verification_status,
        facility_type=facility_type,
        limit=limit,
    )
    return {
        "count": len(items),
        "items": items,
        "important": "Newly entered facilities are unverified until checked against a reliable source.",
    }


@app.post("/facilities", status_code=201)
def add_facility(payload: FacilityRequest):
    facility_id = create_facility(
        name=payload.name.strip(),
        facility_type=payload.facility_type,
        latitude=payload.latitude,
        longitude=payload.longitude,
        address=payload.address.strip() if payload.address else None,
        phone=payload.phone.strip() if payload.phone else None,
        source_name=payload.source_name.strip() if payload.source_name else None,
    )
    return {
        "status": "created",
        "facility_id": facility_id,
        "verification_status": "unverified",
        "message": "Facility saved as unverified. Check its location, service and phone number before relying on it.",
    }


@app.post("/facilities/{facility_id}/verification")
def verify_facility(
    facility_id: int,
    payload: FacilityVerificationRequest,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    configured_token = os.getenv("FACILITY_ADMIN_TOKEN", "")
    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="Facility verification is disabled. Configure FACILITY_ADMIN_TOKEN first.",
        )
    if not x_admin_token or not secrets.compare_digest(configured_token, x_admin_token):
        raise HTTPException(status_code=403, detail="Invalid facility administration token.")

    updated = set_facility_verification(
        facility_id,
        payload.verification_status,
        payload.verification_note.strip(),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Facility not found.")
    return {
        "status": "updated",
        "facility_id": facility_id,
        "verification_status": payload.verification_status,
    }


@app.put("/facilities/{facility_id}")
def edit_facility(facility_id: int, payload: FacilityRequest):
    updated = update_facility(
        facility_id=facility_id,
        name=payload.name.strip(),
        facility_type=payload.facility_type,
        latitude=payload.latitude,
        longitude=payload.longitude,
        address=payload.address.strip() if payload.address else None,
        phone=payload.phone.strip() if payload.phone else None,
        source_name=payload.source_name.strip() if payload.source_name else None,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Facility not found.")
    return {
        "status": "updated",
        "facility_id": facility_id,
        "verification_status": "unverified",
        "message": "Facility details changed; its verification status has been reset.",
    }


@app.delete("/facilities/{facility_id}")
def remove_facility(facility_id: int):
    deleted = delete_facility(facility_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Facility not found.")
    return {"status": "deleted", "facility_id": facility_id}


@app.get("/facilities/nearby")
def nearby_facilities(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=10, gt=0, le=200),
    facility_type: Optional[str] = None,
    verified_only: bool = False,
):
    results = []
    facilities = get_all_facilities(
        verification_status="verified" if verified_only else None,
        facility_type=facility_type,
    )
    for facility in facilities:
        if facility_type and facility["facility_type"].casefold() != facility_type.casefold():
            continue
        distance = haversine_km(
            latitude,
            longitude,
            float(facility["latitude"]),
            float(facility["longitude"]),
        )
        if distance <= radius_km:
            results.append({**facility, "distance_km": round(distance, 2)})

    results.sort(key=lambda item: item["distance_km"])
    return {
        "count": len(results),
        "radius_km": radius_km,
        "verified_only": verified_only,
        "items": results,
        "important": "Distance is straight-line distance, not driving time. Unverified facilities must be checked before use.",
    }
