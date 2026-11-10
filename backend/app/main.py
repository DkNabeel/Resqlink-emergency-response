import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.database.alert_repository import (
    get_active_alerts,
    get_alert_count,
    get_feed_state,
    get_recent_alerts,
)
from app.database.facility_repository import get_all_facilities
from app.database.init_db import create_tables
from app.database.location_repository import get_last_location, save_location
from app.services.geospatial_service import haversine_km, match_alert_location
from app.services.location_service import estimate_location_from_ip
from app.services.sachet_service import DEFAULT_SACHET_FEED, sync_sachet_feed


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("resqlink")

SACHET_FEED_URL = os.getenv("SACHET_FEED_URL", DEFAULT_SACHET_FEED)


async def _alert_refresh_loop():
    interval = max(60, int(os.getenv("SACHET_REFRESH_SECONDS", "300")))
    while True:
        try:
            result = await sync_sachet_feed(SACHET_FEED_URL)
            logger.info(
                "SACHET sync finished: status=%s, items=%s",
                result["status"],
                result["new_alerts"],
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
    version="0.2.0",
    lifespan=lifespan,
)


class EmergencyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


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
    except (TypeError, ValueError):
        return None


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
    }


@app.post("/emergency")
def receive_emergency(request: EmergencyRequest):
    # Gemini remains a separate service until its live API response is verified.
    # This endpoint intentionally does not claim that AI guidance was generated.
    return {
        "status": "received",
        "message": request.message.strip(),
        "ai_status": "not_connected_yet",
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
        return {
            "location_available": True,
            "location_is_current": payload.source == "gps",
            "is_approximate": payload.source != "gps",
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "source": payload.source,
            "accuracy_m": payload.accuracy_m,
            "city": payload.city,
            "district": payload.district,
            "state": payload.state,
            "country": payload.country,
            "message": (
                "Current GPS location received."
                if payload.source == "gps"
                else "Manually selected location saved."
            ),
        }

    client_ip = request.client.host if request.client else None
    if client_ip:
        estimate = await estimate_location_from_ip(client_ip)
        if estimate:
            return {
                "location_available": True,
                "location_is_current": False,
                **estimate,
            }

    last_location = get_last_location(payload.device_id)
    if last_location:
        return {
            "location_available": True,
            "location_is_current": False,
            "is_approximate": last_location["source"] == "ip",
            **last_location,
            "age_minutes": _location_age_minutes(last_location["recorded_at"]),
            "message": (
                "Using the last saved location. It may no longer represent "
                "the device's current position."
            ),
        }

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
    return {
        "location_available": True,
        "location_is_current": False,
        "is_approximate": record["source"] == "ip",
        **record,
        "age_minutes": _location_age_minutes(record["recorded_at"]),
    }


@app.get("/facilities")
def list_facilities():
    items = get_all_facilities()
    return {"count": len(items), "items": items}


@app.get("/facilities/nearby")
def nearby_facilities(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=10, gt=0, le=200),
    facility_type: Optional[str] = None,
):
    results = []
    for facility in get_all_facilities():
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
        "items": results,
    }
