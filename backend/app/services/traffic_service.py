"""OpenRouteService adapter for road-based driving ETA (no live traffic)."""
import os
from datetime import datetime, timezone

import httpx

ROUTES_URL = (
    "https://api.heigit.org/openrouteservice/v2/directions/driving-car"
)


class TrafficNotConfigured(RuntimeError):
    pass


class TrafficServiceError(RuntimeError):
    pass


def normalize_route_response(payload):
    """Normalize an OpenRouteService directions response."""
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not routes:
        raise TrafficServiceError("The route provider returned no driving route.")

    route = routes[0]
    summary = route.get("summary") or {}
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

    geometry = route.get("geometry")
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
    api_key=None,
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

    # Cloudflare Worker secrets are passed explicitly by the Worker binding.
    # The optional fallback preserves the original standalone FastAPI backend.
    if api_key is None:
        api_key = os.getenv("OPENROUTESERVICE_API_KEY", "")
    api_key = str(api_key or "").strip()
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
        "Accept-Encoding": "identity",
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
        raise TrafficServiceError(
            f"OpenRouteService returned HTTP {status}. Check the API key, "
            "account access and request quota."
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise TrafficServiceError(
            f"Driving route request failed: {type(exc).__name__}."
        ) from exc

    return normalize_route_response(data)
