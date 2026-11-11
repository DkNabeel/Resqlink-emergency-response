"""Google Routes API adapter for traffic-aware driving ETA."""
import os
import re
from datetime import datetime, timezone

import httpx

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = (
    "routes.duration,routes.staticDuration,routes.distanceMeters,"
    "routes.polyline.encodedPolyline"
)


class TrafficNotConfigured(RuntimeError):
    pass


class TrafficServiceError(RuntimeError):
    pass


def _duration_seconds(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)s", value.strip())
    return float(match.group(1)) if match else None


def normalize_route_response(payload):
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not routes:
        raise TrafficServiceError("The route provider returned no driving route.")
    route = routes[0]
    duration = _duration_seconds(route.get("duration"))
    typical = _duration_seconds(route.get("staticDuration"))
    distance = route.get("distanceMeters")
    if duration is None or not isinstance(distance, (int, float)) or distance < 0:
        raise TrafficServiceError("The route response is missing a valid ETA or distance.")
    delay = max(0, duration - typical) if typical is not None else None
    polyline = (route.get("polyline") or {}).get("encodedPolyline")
    return {
        "provider": "Google Maps Routes API",
        "travel_mode": "DRIVE",
        "routing_preference": "TRAFFIC_AWARE",
        "traffic_aware_eta_seconds": round(duration),
        "traffic_aware_eta_minutes": round(duration / 60, 1),
        "typical_eta_seconds": round(typical) if typical is not None else None,
        "estimated_traffic_delay_minutes": round(delay / 60, 1) if delay is not None else None,
        "distance_meters": round(distance),
        "distance_km": round(distance / 1000, 2),
        "encoded_polyline": polyline,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "note": "Traffic-aware estimate from the route provider; conditions and coverage vary.",
    }


async def get_traffic_route(origin_latitude, origin_longitude, destination_latitude, destination_longitude):
    try:
        origin_latitude, origin_longitude, destination_latitude, destination_longitude = (
            float(origin_latitude), float(origin_longitude),
            float(destination_latitude), float(destination_longitude),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("All route coordinates must be numbers.") from exc
    if not (-90 <= origin_latitude <= 90 and -90 <= destination_latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (-180 <= origin_longitude <= 180 and -180 <= destination_longitude <= 180):
        raise ValueError("Longitude must be between -180 and 180.")

    api_key = (
        os.getenv("GOOGLE_MAPS_ROUTES_API_KEY", "").strip()
        or os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    )
    if not api_key:
        raise TrafficNotConfigured(
            "Configure GOOGLE_MAPS_ROUTES_API_KEY to enable traffic-aware routes."
        )

    request_body = {
        "origin": {"location": {"latLng": {
            "latitude": origin_latitude, "longitude": origin_longitude,
        }}},
        "destination": {"location": {"latLng": {
            "latitude": destination_latitude, "longitude": destination_longitude,
        }}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "departureTime": "now",
        "computeAlternativeRoutes": False,
        "languageCode": "en-IN",
        "units": "METRIC",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            response = await client.post(ROUTES_URL, json=request_body, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise TrafficServiceError(
            f"Google Routes API returned HTTP {status}. Check API enablement, billing, key restrictions and quota."
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise TrafficServiceError(
            f"Traffic route request failed: {type(exc).__name__}."
        ) from exc
    return normalize_route_response(data)
