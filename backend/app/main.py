import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

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
from app.services.emergency_service import build_emergency_response
from app.services.geospatial_service import haversine_km, match_alert_location
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
    version="0.3.0",
    lifespan=lifespan,
)


class EmergencyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    language: Literal["en", "hi", "kn"] = "en"
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=10, gt=0, le=200)
    city: Optional[str] = Field(default=None, max_length=120)
    district: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=120)


class FacilityRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    facility_type: Literal["hospital", "police", "fire_station", "ambulance", "shelter", "other"]
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: Optional[str] = Field(default=None, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=40)
    source_name: Optional[str] = Field(default=None, max_length=200)


class FacilityVerificationRequest(BaseModel):
    verification_status: Literal["verified", "unverified"]
    verification_note: str = Field(min_length=8, max_length=500)


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
            "gemini": {
                "api_key_configured": bool(os.getenv("GEMINI_API_KEY")),
                "endpoint_connected": False,
                "note": "Gemini is not currently used by POST /emergency.",
            },
        },
        "mobile": {
            "native_app": "not_implemented",
            "on_device_offline_cache": "not_implemented",
            "push_notifications": "not_implemented",
        },
    }


@app.post("/emergency")
def receive_emergency(request: EmergencyRequest):
    has_latitude = request.latitude is not None
    has_longitude = request.longitude is not None
    if has_latitude != has_longitude:
        raise HTTPException(
            status_code=422,
            detail="Send both latitude and longitude, or send neither.",
        )

    result = build_emergency_response(request.message.strip(), request.language)
    nearby_facilities = []
    nearby_alerts = []
    unverified_alerts = []

    if has_latitude and has_longitude:
        for facility in get_all_facilities():
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

    return {
        "status": "processed",
        "message": request.message.strip(),
        **result,
        "analysis_engine": "local_multilingual_nlp_fallback",
        "gemini_status": "not_connected",
        "location_used": (
            {"latitude": request.latitude, "longitude": request.longitude, "radius_km": request.radius_km}
            if has_latitude else None
        ),
        "nearby_facilities": nearby_facilities,
        "nearby_alerts": nearby_alerts,
        "unverified_alerts": unverified_alerts,
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
    x_admin_token: Optional[str] = None,
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
