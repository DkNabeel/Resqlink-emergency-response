"""OpenStreetMap Overpass discovery of nearby facility candidates.

Returned places are community-mapped candidates. They are never stored or
verified automatically and must be checked against an official local source.
"""
import asyncio
import math
import os
import time

import httpx

from app.services.geospatial_service import haversine_km

# Public Overpass instances are best-effort and can be overloaded. Prefer a
# separate operator, then fail over instead of treating one HTTP 502 as no data.
_configured_overpass_url = os.getenv("OVERPASS_URL", "").strip()
# overpass.osm.ch is a Switzerland-only regional replica; it returns a
# successful empty result for Indian coordinates, so never use it in India.
_candidates = (
    _configured_overpass_url,
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
OVERPASS_URLS = tuple(dict.fromkeys(
    url for url in _candidates
    if url and "overpass.osm.ch" not in url.lower()
))
CACHE_SECONDS = 600
EMPTY_CACHE_SECONDS = 20
_CACHE = {}
_CACHE_LOCK = asyncio.Lock()


def _facility_type(tags):
    """Map useful public-service/community tags without requiring a name tag."""
    amenity = str(tags.get("amenity") or "").strip().lower()
    emergency = str(tags.get("emergency") or "").strip().lower()
    healthcare = str(tags.get("healthcare") or "").strip().lower()
    building = str(tags.get("building") or "").strip().lower()

    amenity_types = {
        "hospital": "hospital",
        "police": "police",
        "fire_station": "fire_station",
        "shelter": "shelter",
        "ambulance_station": "ambulance",
        "clinic": "clinic",
        "doctors": "clinic",
        "pharmacy": "pharmacy",
        "school": "education",
        "college": "education",
        "university": "education",
        "community_centre": "community_center",
        "social_facility": "community_center",
        "healthcare": "clinic",
        "rescue_station": "other",
        "first_aid": "other",
    }
    if amenity in amenity_types:
        return amenity_types[amenity]

    emergency_types = {
        "ambulance_station": "ambulance",
        "fire_service": "fire_station",
        "assembly_point": "assembly_point",
        "shelter": "shelter",
        "rescue": "other",
    }
    if emergency in emergency_types:
        return emergency_types[emergency]

    healthcare_types = {
        "hospital": "hospital",
        "clinic": "clinic",
        "doctor": "clinic",
        "pharmacy": "pharmacy",
        "dentist": "clinic",
        "physiotherapist": "clinic",
        "centre": "clinic",
        "healthcare": "clinic",
        "blood_bank": "clinic",
        "birthing_centre": "clinic",
    }
    if healthcare in healthcare_types:
        return healthcare_types[healthcare]

    building_types = {
        "school": "education",
        "college": "education",
        "university": "education",
        "hospital": "hospital",
        "clinic": "clinic",
        "healthcare": "clinic",
    }
    if building in building_types:
        return building_types[building]
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
    if cached:
        ttl = CACHE_SECONDS if cached["result"].get("count", 0) > 0 else EMPTY_CACHE_SECONDS
        if time.monotonic() - cached["at"] < ttl:
            return {**cached["result"], "cache_status": "cached"}

    radius_m = int(radius_km * 1000)
    # A bounding-box query is cheaper for Overpass than several large
    # around() scans. normalize_overpass_elements applies the exact circular
    # haversine radius afterward, so corner features are not shown.
    latitude_delta = radius_m / 111_320
    longitude_delta = radius_m / (111_320 * max(0.01, math.cos(math.radians(latitude))))
    south = max(-90.0, latitude - latitude_delta)
    north = min(90.0, latitude + latitude_delta)
    west = max(-180.0, longitude - longitude_delta)
    east = min(180.0, longitude + longitude_delta)
    bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"

    # Search all nearby emergency/public-service and community facilities,
    # not only the facility types suggested for the currently reported hazard.
    # Schools/colleges are community places, never verified shelters.
    query = f"""
[out:json][timeout:30];
(
  nwr["amenity"~"^(hospital|police|fire_station|shelter|ambulance_station|clinic|doctors|pharmacy|school|college|university|community_centre|social_facility|healthcare|rescue_station|first_aid)$"]({bbox});
  nwr["emergency"~"^(ambulance_station|fire_service|assembly_point|shelter|rescue)$"]({bbox});
  nwr["healthcare"]({bbox});
  nwr["building"~"^(hospital|clinic|healthcare|school|college|university)$"]({bbox});
);
out center tags;
""".strip()

    async with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached:
            ttl = CACHE_SECONDS if cached["result"].get("count", 0) > 0 else EMPTY_CACHE_SECONDS
            if time.monotonic() - cached["at"] < ttl:
                return {**cached["result"], "cache_status": "cached"}
        failures = []
        data = None
        empty_response = None
        successful_endpoint = None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=4.0),
            headers={
                "User-Agent": "ResQLink-EmergencyResponse/1.1 (emergency facility discovery)",
                "Accept": "application/json",
            },
        ) as client:
            for endpoint_index, endpoint in enumerate(OVERPASS_URLS):
                try:
                    # Allow a little more than the 30-second Overpass query budget,
                    # while keeping fallback endpoints bounded.
                    request_timeout = httpx.Timeout(
                        38.0 if endpoint_index == 0 else 20.0,
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
                    # Overpass can return HTTP 200 with an empty elements array
                    # and a JSON "remark" describing a timeout/runtime failure.
                    # Treat that as a failed query and try the next global server.
                    remark = candidate_data.get("remark")
                    if isinstance(remark, str) and remark.strip():
                        failures.append(f"{endpoint}: {remark.strip()[:180]}")
                        continue
                    if candidate_data["elements"]:
                        data = candidate_data
                        successful_endpoint = endpoint
                        break
                    # Some public instances can return an empty snapshot while
                    # another has the same OSM data. Try the next endpoint before
                    # telling the app that the area has no mapped services.
                    empty_response = candidate_data
                    successful_endpoint = endpoint
                except (httpx.HTTPError, ValueError) as exc:
                    failures.append(f"{endpoint}: {type(exc).__name__}")

        if data is None:
            data = empty_response
        if data is None:
            raise RuntimeError(
                "All OpenStreetMap Overpass endpoints failed (" + "; ".join(failures) + ")."
            )

        elements = data.get("elements") or []
        items = normalize_overpass_elements(elements, latitude, longitude, radius_km)
        result = {
            "count": len(items),
            "items": items,
            "source": "OpenStreetMap contributors",
            "attribution": "© OpenStreetMap contributors",
            "radius_km": radius_km,
            "raw_element_count": len(elements),
            "excluded_element_count": max(0, len(elements) - len(items)),
            "provider_endpoint": successful_endpoint,
            "osm_data_timestamp": (data.get("osm3s") or {}).get("timestamp_osm_base"),
            "note": (
                "Includes hospitals, clinics, healthcare centres, pharmacies, police, fire stations, "
                "ambulance and rescue services, shelters and nearby schools/colleges/universities. "
                "All are unverified OpenStreetMap candidates; education/community places "
                "are not designated shelters unless authorities confirm them."
            ),
        }
        _CACHE[key] = {"at": time.monotonic(), "result": result}
        return {**result, "cache_status": "live"}


def clear_discovery_cache():
    _CACHE.clear()
