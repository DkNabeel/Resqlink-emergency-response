"""OpenStreetMap Overpass discovery of nearby facility candidates.

Returned places are community-mapped candidates. They are never stored or
verified automatically and must be checked against an official local source.
"""
import asyncio
import time

import httpx

from app.services.geospatial_service import haversine_km

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CACHE_SECONDS = 900
_CACHE = {}
_CACHE_LOCK = asyncio.Lock()


def _facility_type(tags):
    amenity = str(tags.get("amenity") or "").lower()
    emergency = str(tags.get("emergency") or "").lower()
    healthcare = str(tags.get("healthcare") or "").lower()
    if amenity in {"hospital", "police", "fire_station", "shelter"}:
        return amenity
    if emergency == "ambulance_station":
        return "ambulance"
    if healthcare == "hospital":
        return "hospital"
    if healthcare in {"clinic", "doctor"}:
        return "other"
    return None


def normalize_overpass_elements(elements, origin_latitude, origin_longitude, radius_km):
    result = []
    seen = set()
    for element in elements or []:
        tags = element.get("tags") or {}
        name = str(tags.get("name") or tags.get("name:en") or "").strip()
        facility_type = _facility_type(tags)
        if not name or not facility_type:
            continue

        latitude, longitude = element.get("lat"), element.get("lon")
        if latitude is None or longitude is None:
            center = element.get("center") or {}
            latitude, longitude = center.get("lat"), center.get("lon")
        try:
            latitude, longitude = float(latitude), float(longitude)
        except (TypeError, ValueError):
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue

        distance = haversine_km(origin_latitude, origin_longitude, latitude, longitude)
        if distance > radius_km:
            continue
        identity = (facility_type, name.casefold(), round(latitude, 4), round(longitude, 4))
        if identity in seen:
            continue
        seen.add(identity)

        address_parts = (
            tags.get("addr:housenumber"), tags.get("addr:street"),
            tags.get("addr:suburb"), tags.get("addr:city"),
        )
        address = ", ".join(str(part) for part in address_parts if part) or None
        source_type, source_id = element.get("type"), element.get("id")
        result.append({
            "name": name,
            "facility_type": facility_type,
            "latitude": latitude,
            "longitude": longitude,
            "distance_km": round(distance, 2),
            "address": address,
            "phone": tags.get("contact:phone") or tags.get("phone"),
            "source_name": "OpenStreetMap contributors",
            "source_url": (
                f"https://www.openstreetmap.org/{source_type}/{source_id}"
                if source_type and source_id else None
            ),
            "verification_status": "unverified",
            "verification_warning": (
                "Community-mapped candidate only. Confirm that the facility exists, is "
                "open and provides this service before using or verifying it."
            ),
        })
    result.sort(key=lambda item: item["distance_km"])
    return result


async def discover_facilities(latitude, longitude, radius_km=5):
    latitude, longitude, radius_km = float(latitude), float(longitude), float(radius_km)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Coordinates are outside valid latitude/longitude ranges.")
    if not (1 <= radius_km <= 20):
        raise ValueError("Discovery radius must be between 1 and 20 km.")

    key = (round(latitude, 4), round(longitude, 4), round(radius_km, 1))
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached["at"] < CACHE_SECONDS:
        return {**cached["result"], "cache_status": "cached"}

    radius_m = int(radius_km * 1000)
    query = f"""
[out:json][timeout:18];
(
  nwr(around:{radius_m},{latitude},{longitude})["amenity"~"hospital|police|fire_station|shelter"];
  nwr(around:{radius_m},{latitude},{longitude})["emergency"="ambulance_station"];
  nwr(around:{radius_m},{latitude},{longitude})["healthcare"~"hospital|clinic|doctor"];
);
out center tags;
""".strip()

    async with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached["at"] < CACHE_SECONDS:
            return {**cached["result"], "cache_status": "cached"}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(22.0, connect=5.0),
                headers={
                    "User-Agent": "ResQLink-EmergencyResponse/1.0",
                    "Accept-Encoding": "identity",
                },
            ) as client:
                response = await client.post(OVERPASS_URL, data={"data": query})
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(
                f"OpenStreetMap discovery failed: {type(exc).__name__}."
            ) from exc

        elements = data.get("elements") if isinstance(data, dict) else None
        if not isinstance(elements, list):
            raise RuntimeError("OpenStreetMap returned an unexpected response.")
        items = normalize_overpass_elements(elements, latitude, longitude, radius_km)
        result = {
            "count": len(items),
            "items": items,
            "source": "OpenStreetMap contributors",
            "attribution": "© OpenStreetMap contributors",
            "radius_km": radius_km,
            "note": "All discovered places are candidates and remain unverified; check official local records.",
        }
        _CACHE[key] = {"at": time.monotonic(), "result": result}
        return {**result, "cache_status": "live"}


def clear_discovery_cache():
    _CACHE.clear()
