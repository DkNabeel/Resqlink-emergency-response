"""OpenRouteService adapter for road-based driving ETA (no live traffic)."""
import os
from datetime import datetime, timezone

import httpx

ROUTES_URL = (
    "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson"
)


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
