"""OpenStreetMap Overpass discovery of nearby facility candidates.

Returned places are community-mapped candidates. They are never stored or
verified automatically and must be checked against an official local source.
"""
import asyncio
import os
import time

import httpx

from app.services.geospatial_service import haversine_km

# Public Overpass instances are best-effort and can be overloaded. Prefer a
# separate operator, then fail over instead of treating one HTTP 502 as no data.
_configured_overpass_url = os.getenv("OVERPASS_URL", "").strip()
OVERPASS_URLS = tuple(dict.fromkeys(url for url in (
    _configured_overpass_url,
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
) if url))
CACHE_SECONDS = 600
_CACHE = {}
_CACHE_LOCK = asyncio.Lock()


def _facility_type(tags):
    """Map a wider set of useful community-mapped places without treating them as verified."""
    amenity = str(tags.get("amenity") or "").strip().lower()
    emergency = str(tags.get("emergency") or "").strip().lower()
    healthcare = str(tags.get("healthcare") or "").strip().lower()
    education = str(tags.get("education") or "").strip().lower()

    direct_types = {
        "hospital": "hospital",
        "police": "police",
        "fire_station": "fire_station",
        "shelter": "shelter",
        "clinic": "clinic",
        "doctors": "clinic",
        "college": "college",
        "university": "college",
        "school": "school",
    }
    if amenity in direct_types:
        return direct_types[amenity]
    if emergency == "ambulance_station":
        return "ambulance"
    if emergency == "fire_service":
        return "fire_station"
    if emergency == "police":
        return "police"
    if healthcare == "hospital":
        return "hospital"
    if healthcare in {"clinic", "doctor", "centre", "center"}:
        return "clinic"
    if education in {"college", "university"}:
        return "college"
    return None


def normalize_overpass_elements(elements, origin_latitude, origin_longitude, radius_km):
    result = []
    seen = set()
    for element in elements or []:
        tags = element.get("tags") or {}
        name = str(tags.get("name") or tags.get("name:en") or "").strip()
        facility_type = _facility_type(tags)
        # Many valid OSM hospitals and shelters are mapped without a name tag.
        # Keep them when their facility type and coordinates are usable; attach
        # a clearly inferred label instead of silently dropping the map feature.
        if not facility_type:
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
        source_type, source_id = element.get("type"), element.get("id")
        address = str(tags.get("addr:full") or "").strip() or None
        if not address:
            address_parts = (
                tags.get("addr:housenumber"), tags.get("addr:street"),
                tags.get("addr:suburb"), tags.get("addr:city"),
                tags.get("addr:district"), tags.get("addr:state"),
            )
            address = ", ".join(str(part) for part in address_parts if part) or None

        facility_label = facility_type.replace("_", " ").title()
        if name:
            display_name = name
        elif address:
            display_name = f"{facility_label} near {address}"
        elif source_type and source_id is not None:
            display_name = f"Unnamed {facility_label} (OSM {source_type}/{source_id})"
        else:
            display_name = f"Unnamed {facility_label} at {latitude:.5f}, {longitude:.5f}"

        if name:
            identity = (facility_type, name.casefold(), round(latitude, 4), round(longitude, 4))
        elif source_type and source_id is not None:
            identity = ("osm", source_type, str(source_id))
        else:
            identity = (facility_type, display_name.casefold(), round(latitude, 4), round(longitude, 4))
        if identity in seen:
            continue
        seen.add(identity)

        result.append({
            "name": display_name,
            "osm_name": name or None,
            "has_map_name": bool(name),
            "osm_element_type": source_type,
            "osm_id": source_id,
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
    if cached and time.monotonic() - cached["at"] < cached.get("ttl", CACHE_SECONDS):
        return {**cached["result"], "cache_status": "cached"}

    radius_m = int(radius_km * 1000)
    # Include emergency services, medical providers and nearby public
    # educational institutions. These are map candidates, never assumed safe.
    query = f"""
[out:json][timeout:25];
(
  nwr(around:{radius_m},{latitude},{longitude})["amenity"~"hospital|clinic|doctors|police|fire_station|shelter|college|university|school"];
  nwr(around:{radius_m},{latitude},{longitude})["emergency"~"ambulance_station|fire_service|police"];
  nwr(around:{radius_m},{latitude},{longitude})["healthcare"~"hospital|clinic|doctor|centre|center"];
  nwr(around:{radius_m},{latitude},{longitude})["education"~"college|university"];
);
out center tags;
""".strip()

    async with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached["at"] < cached.get("ttl", CACHE_SECONDS):
            return {**cached["result"], "cache_status": "cached"}
        failures = []
        data = None
        provider_used = None
        providers_checked = []
        raw_element_count = 0
        items = []
        # A valid empty response from one public Overpass instance is not
        # definitive: another instance may have a fuller replica. Try the
        # primary and at least one fallback before returning an empty list.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=4.0),
            headers={
                "User-Agent": "ResQLink-EmergencyResponse/1.2 (emergency facility discovery)",
                "Accept": "application/json",
            },
        ) as client:
            for endpoint_index, endpoint in enumerate(OVERPASS_URLS[:2]):
                try:
                    request_timeout = httpx.Timeout(
                        35.0 if endpoint_index == 0 else 12.0,
                        connect=5.0 if endpoint_index == 0 else 4.0,
                    )
                    response = await client.post(
                        endpoint,
                        data={"data": query},
                        timeout=request_timeout,
                    )
                    response.raise_for_status()
                    candidate_data = response.json()
                    if not isinstance(candidate_data, dict) or not isinstance(candidate_data.get("elements"), list):
                        raise ValueError("Unexpected Overpass response shape.")
                    providers_checked.append(endpoint)
                    candidate_elements = candidate_data["elements"]
                    candidate_items = normalize_overpass_elements(
                        candidate_elements, latitude, longitude, radius_km
                    )
                    raw_element_count = max(raw_element_count, len(candidate_elements))
                    if candidate_items:
                        data = candidate_data
                        items = candidate_items
                        provider_used = endpoint
                        break
                    if data is None:
                        data = candidate_data
                        provider_used = endpoint
                except (httpx.HTTPError, ValueError) as exc:
                    failures.append(f"{endpoint}: {type(exc).__name__}")

        if data is None:
            raise RuntimeError(
                "All OpenStreetMap Overpass endpoints failed (" + "; ".join(failures) + ")."
            )

        if not items:
            result = {
                "count": 0,
                "items": [],
                "source": "OpenStreetMap contributors",
                "attribution": "© OpenStreetMap contributors",
                "radius_km": radius_km,
                "raw_element_count": raw_element_count,
                "providers_checked": providers_checked,
                "provider_used": provider_used,
                "note": (
                    "No matching mapped facilities were returned by the checked providers. "
                    "This does not mean no hospitals, colleges or emergency services exist nearby."
                ),
            }
            _CACHE[key] = {"at": time.monotonic(), "result": result, "ttl": 30}
            return {**result, "cache_status": "live_empty"}

        result = {
            "count": len(items),
            "items": items,
            "source": "OpenStreetMap contributors",
            "attribution": "© OpenStreetMap contributors",
            "radius_km": radius_km,
            "raw_element_count": raw_element_count,
            "providers_checked": providers_checked,
            "provider_used": provider_used,
            "note": "OpenStreetMap places are community-mapped candidates and remain unverified; confirm service and opening status locally.",
        }
        _CACHE[key] = {"at": time.monotonic(), "result": result}
        return {**result, "cache_status": "live"}


def clear_discovery_cache():
    _CACHE.clear()
