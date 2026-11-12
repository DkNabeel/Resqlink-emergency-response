"""HeiGIT/OpenRouteService adapters for road-based driving distance and ETA."""
import asyncio
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone

import httpx

ROUTES_URL = (
    "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson"
)
MATRIX_URL = "https://api.heigit.org/openrouteservice/v2/matrix/driving-car"

# HeiGIT hosted requests with dynamic arguments allow 25 locations total:
# one origin plus up to 24 facility destinations per Matrix call.
# Cache successful matrices for five minutes and briefly cool down failed keys
# so retries, GPS refreshes, or repeated renders cannot hammer HeiGIT.
MATRIX_MAX_DESTINATIONS = 24
MATRIX_CACHE_TTL_SECONDS = 300
MATRIX_FAILURE_COOLDOWN_SECONDS = 45
MATRIX_CACHE_MAX_ENTRIES = 64
_MATRIX_CACHE = {}
_MATRIX_FAILURE_CACHE = {}
_MATRIX_REQUEST_LOCK = asyncio.Lock()


class TrafficNotConfigured(RuntimeError):
    pass


class TrafficServiceError(RuntimeError):
    pass


def _provider_error_message(response):
    """Extract a safe, concise provider error without exposing request headers."""
    message = ""
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("description") or "").strip()
            code = error.get("code")
            if code is not None:
                message = (message + f" (provider code {code})").strip()
        elif isinstance(error, str):
            message = error.strip()
        if not message:
            message = str(payload.get("message") or payload.get("description") or "").strip()

    if not message:
        try:
            message = str(response.text or "").strip()
        except Exception:
            message = ""
    return message[:320]


def normalize_route_response(payload):
    """Normalize an OpenRouteService directions response."""
    routes = payload.get("routes") if isinstance(payload, dict) else None
    features = payload.get("features") if isinstance(payload, dict) else None
    if routes:
        route = routes[0]
        summary = route.get("summary") or {}
        geometry = route.get("geometry")
    elif features:
        # The /geojson endpoint returns a FeatureCollection. ORS keeps the
        # route summary in feature.properties and the LineString in geometry.
        route = features[0]
        properties = route.get("properties") or {}
        summary = properties.get("summary") or {}
        geometry = route.get("geometry")
    else:
        raise TrafficServiceError("The route provider returned no driving route.")

    duration = summary.get("duration")
    distance = summary.get("distance")
    if (
        not isinstance(duration, (int, float))
        or duration < 0
        or not isinstance(distance, (int, float))
        or distance < 0
    ):
        raise TrafficServiceError(
            "The route response is missing a valid ETA or distance."
        )

    encoded_polyline = geometry if isinstance(geometry, str) else None
    route_geometry = geometry if isinstance(geometry, dict) else None

    return {
        "provider": "OpenRouteService (HeiGIT)",
        "travel_mode": "DRIVE",
        "routing_preference": "recommended",
        "live_traffic_available": False,
        "estimated_travel_time_seconds": round(duration),
        "estimated_travel_time_minutes": round(duration / 60, 1),
        "distance_meters": round(distance),
        "distance_km": round(distance / 1000, 2),
        "encoded_polyline": encoded_polyline,
        "route_geometry": route_geometry,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Road-network travel-time estimate from OpenRouteService. "
            "Live traffic conditions and congestion are not included."
        ),
    }


async def get_traffic_route(
    origin_latitude,
    origin_longitude,
    destination_latitude,
    destination_longitude,
):
    try:
        origin_latitude, origin_longitude, destination_latitude, destination_longitude = (
            float(origin_latitude),
            float(origin_longitude),
            float(destination_latitude),
            float(destination_longitude),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("All route coordinates must be numbers.") from exc

    if not (-90 <= origin_latitude <= 90 and -90 <= destination_latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (
        -180 <= origin_longitude <= 180
        and -180 <= destination_longitude <= 180
    ):
        raise ValueError("Longitude must be between -180 and 180.")

    api_key = os.getenv("OPENROUTESERVICE_API_KEY", "").strip()
    # HeiGIT expects the key itself in Authorization, not "Bearer <key>".
    # Accept either .env style so an accidental prefix does not cause a 403.
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:].strip()
    if not api_key:
        raise TrafficNotConfigured(
            "Configure OPENROUTESERVICE_API_KEY to enable driving routes."
        )

    request_body = {
        "coordinates": [
            [origin_longitude, origin_latitude],
            [destination_longitude, destination_latitude],
        ],
        "preference": "recommended",
        "units": "m",
        "instructions": False,
        "geometry": True,
    }
    headers = {
        "Authorization": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=4.0)
        ) as client:
            response = await client.post(
                ROUTES_URL,
                json=request_body,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        provider_message = _provider_error_message(exc.response)
        if status == 403:
            detail = f" HeiGIT says: {provider_message}." if provider_message else ""
            raise TrafficServiceError(
                "HeiGIT denied the driving-route request (HTTP 403)." + detail
                + " This is an upstream access refusal, not a ResQLink network failure. "
                + "If the provider says access is disallowed, copy the complete API key "
                + "from account.heigit.org using its Copy button and paste the raw key "
                + "into backend/.env as OPENROUTESERVICE_API_KEY. Do not use the masked "
                + "key preview; a daily quota limit can also cause HTTP 403."
            ) from exc
        if status == 401:
            raise TrafficServiceError(
                "HeiGIT rejected the route API key (HTTP 401). Check that "
                "OPENROUTESERVICE_API_KEY contains the full, current key."
                + (f" Provider message: {provider_message}" if provider_message else "")
            ) from exc
        if status == 429:
            raise TrafficServiceError(
                "HeiGIT route request limit reached (HTTP 429). Wait for the "
                "minute-level limit to reset before retrying."
                + (f" Provider message: {provider_message}" if provider_message else "")
            ) from exc
        raise TrafficServiceError(
            f"OpenRouteService returned HTTP {status}."
            + (f" Provider message: {provider_message}" if provider_message else "")
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise TrafficServiceError(
            f"Driving route request failed: {type(exc).__name__}."
        ) from exc

    return normalize_route_response(data)


def _normalize_api_key():
    api_key = os.getenv("OPENROUTESERVICE_API_KEY", "").strip()
    # HeiGIT expects the key itself in Authorization, not "Bearer <key>".
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:].strip()
    return api_key


def normalize_matrix_response(payload, expected_destinations):
    """Normalize the first-source row from a HeiGIT distance/duration matrix."""
    distances = payload.get("distances") if isinstance(payload, dict) else None
    durations = payload.get("durations") if isinstance(payload, dict) else None
    if (
        not isinstance(distances, list)
        or not distances
        or not isinstance(distances[0], list)
        or not isinstance(durations, list)
        or not durations
        or not isinstance(durations[0], list)
    ):
        raise TrafficServiceError(
            "HeiGIT returned a matrix without distance and duration rows."
        )

    distance_row = distances[0]
    duration_row = durations[0]
    if (
        len(distance_row) != expected_destinations
        or len(duration_row) != expected_destinations
    ):
        raise TrafficServiceError(
            "HeiGIT returned a matrix with an unexpected number of destinations."
        )

    normalized = []
    for distance, duration in zip(distance_row, duration_row):
        valid_distance = (
            isinstance(distance, (int, float))
            and math.isfinite(distance)
            and distance >= 0
        )
        valid_duration = (
            isinstance(duration, (int, float))
            and math.isfinite(duration)
            and duration >= 0
        )
        if not valid_distance or not valid_duration:
            normalized.append({
                "road_distance_meters": None,
                "road_distance_km": None,
                "road_duration_seconds": None,
                "road_duration_minutes": None,
                "road_route_status": "unreachable",
            })
            continue

        normalized.append({
            "road_distance_meters": round(distance),
            "road_distance_km": round(distance / 1000, 2),
            "road_duration_seconds": round(duration),
            "road_duration_minutes": round(duration / 60, 1),
            "road_route_status": "available",
        })
    return normalized


def clear_traffic_matrix_cache():
    """Clear in-memory matrix caches (also useful for isolated service tests)."""
    _MATRIX_CACHE.clear()
    _MATRIX_FAILURE_CACHE.clear()


def _matrix_cache_key(origin_latitude, origin_longitude, destination_keys):
    # A 4-decimal origin bucket absorbs small GPS jitter (~11 m); facility
    # coordinates remain at 5 decimals. Cached values are mapped by coordinate.
    material = {
        "origin": [round(origin_latitude, 4), round(origin_longitude, 4)],
        "destinations": sorted(destination_keys),
    }
    return hashlib.sha256(
        json.dumps(material, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _trim_matrix_cache(cache):
    while len(cache) > MATRIX_CACHE_MAX_ENTRIES:
        oldest_key = min(cache, key=lambda key: cache[key][0])
        cache.pop(oldest_key, None)


async def get_traffic_matrix(origin_latitude, origin_longitude, destinations):
    """Get road distance and ETA to many facilities with one cached Matrix call.

    destinations is an ordered sequence of (latitude, longitude) pairs.
    Results are returned in the same order, including duplicate destinations.
    """
    try:
        origin_latitude = float(origin_latitude)
        origin_longitude = float(origin_longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("Origin coordinates must be numbers.") from exc

    if not (-90 <= origin_latitude <= 90 and -180 <= origin_longitude <= 180):
        raise ValueError("Origin coordinates are outside valid latitude/longitude ranges.")

    if len(destinations) > MATRIX_MAX_DESTINATIONS:
        raise ValueError(
            f"At most {MATRIX_MAX_DESTINATIONS} facility destinations can be routed in one matrix request."
        )

    parsed_destinations = []
    for destination in destinations:
        try:
            latitude, longitude = float(destination[0]), float(destination[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError("Every destination must contain latitude and longitude.") from exc
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Destination coordinates are outside valid latitude/longitude ranges.")
        parsed_destinations.append((latitude, longitude))

    if not parsed_destinations:
        return {
            "items": [],
            "provider": "OpenRouteService (HeiGIT)",
            "cache_status": "not_needed",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    # Deduplicate destination coordinates so duplicate OSM node/way records
    # do not consume additional matrix cells or API quota.
    unique_destinations = []
    unique_keys = []
    seen = set()
    for latitude, longitude in parsed_destinations:
        coordinate_key = (round(latitude, 5), round(longitude, 5))
        if coordinate_key not in seen:
            seen.add(coordinate_key)
            unique_destinations.append((latitude, longitude))
            unique_keys.append(coordinate_key)

    cache_key = _matrix_cache_key(
        origin_latitude, origin_longitude, unique_keys
    )

    # Serialize Matrix requests: even concurrent refreshes from multiple
    # phones cannot create a burst of upstream routing calls.
    async with _MATRIX_REQUEST_LOCK:
        now = time.monotonic()
        cached = _MATRIX_CACHE.get(cache_key)
        if cached and now - cached[0] < MATRIX_CACHE_TTL_SECONDS:
            _, result_by_key, checked_at = cached
            return {
                "items": [
                    dict(result_by_key[(round(lat, 5), round(lon, 5))])
                    for lat, lon in parsed_destinations
                ],
                "provider": "OpenRouteService (HeiGIT)",
                "cache_status": "cached",
                "checked_at": checked_at,
            }
        if cached:
            _MATRIX_CACHE.pop(cache_key, None)

        failed = _MATRIX_FAILURE_CACHE.get(cache_key)
        if failed and now - failed[0] < MATRIX_FAILURE_COOLDOWN_SECONDS:
            raise TrafficServiceError(failed[1])
        if failed:
            _MATRIX_FAILURE_CACHE.pop(cache_key, None)

        api_key = _normalize_api_key()
        if not api_key:
            raise TrafficNotConfigured(
                "Configure OPENROUTESERVICE_API_KEY to enable road distances."
            )

        locations = [[origin_longitude, origin_latitude]] + [
            [longitude, latitude]
            for latitude, longitude in unique_destinations
        ]
        request_body = {
            "locations": locations,
            "sources": ["0"],
            "destinations": [str(index) for index in range(1, len(locations))],
            "metrics": ["distance", "duration"],
            "units": "m",
            "resolve_locations": False,
        }
        headers = {
            "Authorization": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=4.0)
            ) as client:
                response = await client.post(
                    MATRIX_URL,
                    json=request_body,
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            provider_message = _provider_error_message(exc.response)
            if status == 403:
                detail = f" HeiGIT says: {provider_message}." if provider_message else ""
                message = (
                    "HeiGIT denied the road-distance matrix (HTTP 403)." + detail
                    + " Check the complete OPENROUTESERVICE_API_KEY and account quota."
                )
            elif status == 401:
                message = (
                    "HeiGIT rejected the route API key (HTTP 401). Check the full current key."
                    + (f" Provider message: {provider_message}" if provider_message else "")
                )
            elif status == 429:
                message = (
                    "HeiGIT matrix request limit reached (HTTP 429). Wait before retrying."
                    + (f" Provider message: {provider_message}" if provider_message else "")
                )
            else:
                message = (
                    f"HeiGIT matrix request failed with HTTP {status}."
                    + (f" Provider message: {provider_message}" if provider_message else "")
                )
            _MATRIX_FAILURE_CACHE[cache_key] = (time.monotonic(), message)
            _trim_matrix_cache(_MATRIX_FAILURE_CACHE)
            raise TrafficServiceError(message) from exc
        except (httpx.HTTPError, ValueError) as exc:
            message = f"HeiGIT road-distance matrix failed: {type(exc).__name__}."
            _MATRIX_FAILURE_CACHE[cache_key] = (time.monotonic(), message)
            _trim_matrix_cache(_MATRIX_FAILURE_CACHE)
            raise TrafficServiceError(message) from exc

        rows = normalize_matrix_response(payload, len(unique_destinations))
        result_by_key = {
            key: row for key, row in zip(unique_keys, rows)
        }
        checked_at = datetime.now(timezone.utc).isoformat()
        _MATRIX_CACHE[cache_key] = (
            time.monotonic(),
            result_by_key,
            checked_at,
        )
        _trim_matrix_cache(_MATRIX_CACHE)
        _MATRIX_FAILURE_CACHE.pop(cache_key, None)

        return {
            "items": [
                dict(result_by_key[(round(lat, 5), round(lon, 5))])
                for lat, lon in parsed_destinations
            ],
            "provider": "OpenRouteService (HeiGIT)",
            "cache_status": "live",
            "checked_at": checked_at,
        }
