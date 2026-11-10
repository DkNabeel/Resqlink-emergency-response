import ipaddress
import os

import httpx


async def estimate_location_from_ip(ip_address):
    """
    Return a coarse IP-based location estimate.

    This is disabled by default. When enabled, the public IP is sent to the
    configured provider. IP-derived coordinates are approximate and must not
    be used for precise hazard-boundary or evacuation decisions.
    """
    enabled = os.getenv("IP_GEOLOCATION_ENABLED", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None

    try:
        parsed_ip = ipaddress.ip_address(ip_address)
    except ValueError:
        return None

    if (
        parsed_ip.is_private
        or parsed_ip.is_loopback
        or parsed_ip.is_link_local
        or parsed_ip.is_reserved
        or parsed_ip.is_multicast
    ):
        return None

    template = os.getenv(
        "IP_GEOLOCATION_URL_TEMPLATE",
        "https://ipapi.co/{ip}/json/",
    )
    url = template.format(ip=str(parsed_ip))

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    try:
        latitude = float(data["latitude"])
        longitude = float(data["longitude"])
    except (KeyError, TypeError, ValueError):
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    return {
        "latitude": latitude,
        "longitude": longitude,
        "source": "ip",
        "is_approximate": True,
        "accuracy_m": None,
        "city": data.get("city"),
        "district": None,
        "state": data.get("region"),
        "country": data.get("country_name") or data.get("country"),
        "note": (
            "Approximate IP location. It may identify a carrier gateway or "
            "regional centre and must not be used to confirm a person is "
            "inside or outside a dangerous area."
        ),
    }
