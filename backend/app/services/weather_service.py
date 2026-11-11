"""Open-Meteo weather forecast adapter with a short in-memory cache.

Forecast output is contextual information, not an official disaster warning.
Open-Meteo free API use is intended for non-commercial use and requires
attribution; see https://open-meteo.com/en/terms and the API documentation.
"""
import asyncio
import os
import time
from datetime import datetime, timezone

import httpx


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Weather forecast by Open-Meteo (CC BY 4.0)"
DISCLAIMER = (
    "Model-based forecast, not an official warning or a guarantee of local conditions. "
    "Use government alerts and local authority instructions for emergency decisions."
)

WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

_CACHE = {}
_CACHE_LOCK = asyncio.Lock()


class WeatherServiceError(RuntimeError):
    """Raised when a usable weather response cannot be retrieved."""


def clear_weather_cache():
    """Clear cached weather (used by tests and controlled refresh workflows)."""
    _CACHE.clear()


def _weather_label(code):
    try:
        return WMO_CODES.get(int(code), "Unknown weather code")
    except (TypeError, ValueError):
        return "Unknown weather code"


def normalize_weather_payload(data, latitude, longitude, forecast_hours=12):
    current = data.get("current") or {}
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []

    forecast = []
    for index, timestamp in enumerate(times[:forecast_hours]):
        def value_at(key):
            values = hourly.get(key) or []
            return values[index] if index < len(values) else None

        code = value_at("weather_code")
        forecast.append({
            "time": timestamp,
            "weather_code": code,
            "condition": _weather_label(code),
            "precipitation_mm": value_at("precipitation"),
            "precipitation_probability_pct": value_at("precipitation_probability"),
            "wind_speed_kmh": value_at("wind_speed_10m"),
            "wind_gusts_kmh": value_at("wind_gusts_10m"),
            "relative_humidity_pct": value_at("relative_humidity_2m"),
        })

    precipitation_probabilities = [
        item["precipitation_probability_pct"]
        for item in forecast
        if isinstance(item["precipitation_probability_pct"], (int, float))
    ]
    precipitation_amounts = [
        item["precipitation_mm"]
        for item in forecast
        if isinstance(item["precipitation_mm"], (int, float))
    ]
    thunderstorm_hours = [
        item["time"] for item in forecast
        if item["weather_code"] in (95, 96, 99)
    ]

    current_code = current.get("weather_code")
    return {
        "latitude": data.get("latitude", latitude),
        "longitude": data.get("longitude", longitude),
        "timezone": data.get("timezone"),
        "current": {
            "time": current.get("time"),
            "temperature_c": current.get("temperature_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "relative_humidity_pct": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "wind_gusts_kmh": current.get("wind_gusts_10m"),
            "weather_code": current_code,
            "condition": _weather_label(current_code),
        },
        "forecast_hours": forecast,
        "forecast_indicators": {
            "hours_returned": len(forecast),
            "max_precipitation_probability_pct": (
                max(precipitation_probabilities) if precipitation_probabilities else None
            ),
            "total_forecast_precipitation_mm": (
                round(sum(precipitation_amounts), 1) if precipitation_amounts else None
            ),
            "thunderstorm_forecast_times": thunderstorm_hours,
        },
        "source": "Open-Meteo",
        "attribution": ATTRIBUTION,
        "disclaimer": DISCLAIMER,
    }


async def _fetch_open_meteo(latitude, longitude, forecast_hours):
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m,wind_gusts_10m"
        ),
        "hourly": (
            "precipitation_probability,precipitation,weather_code,"
            "wind_speed_10m,wind_gusts_10m,relative_humidity_2m"
        ),
        "forecast_hours": forecast_hours,
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0)) as client:
            response = await client.get(OPEN_METEO_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise WeatherServiceError(
            f"Weather provider request failed: {type(exc).__name__}"
        ) from exc

    if not isinstance(data, dict) or not isinstance(data.get("hourly"), dict):
        raise WeatherServiceError("Weather provider returned an unexpected response.")
    return data


async def get_weather_snapshot(latitude, longitude, forecast_hours=12):
    """Return normalized forecast; cache for 10 minutes and permit stale fallback."""
    if not (-90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180):
        raise ValueError("Coordinates are outside valid latitude/longitude ranges.")
    if not 1 <= int(forecast_hours) <= 24:
        raise ValueError("forecast_hours must be between 1 and 24.")

    ttl_seconds = max(60, int(os.getenv("WEATHER_CACHE_TTL_SECONDS", "600")))
    stale_limit_seconds = max(ttl_seconds, 86400)
    key = (round(float(latitude), 3), round(float(longitude), 3), int(forecast_hours))
    now = time.monotonic()

    cached = _CACHE.get(key)
    if cached and now - cached["cached_at"] <= ttl_seconds:
        result = dict(cached["payload"])
        result["cache_status"] = "cached"
        result["cache_age_seconds"] = int(now - cached["cached_at"])
        return result

    async with _CACHE_LOCK:
        now = time.monotonic()
        cached = _CACHE.get(key)
        if cached and now - cached["cached_at"] <= ttl_seconds:
            result = dict(cached["payload"])
            result["cache_status"] = "cached"
            result["cache_age_seconds"] = int(now - cached["cached_at"])
            return result

        try:
            raw = await _fetch_open_meteo(*key[:2], forecast_hours=key[2])
            normalized = normalize_weather_payload(raw, key[0], key[1], key[2])
            normalized["fetched_at"] = datetime.now(timezone.utc).isoformat()
            _CACHE[key] = {"cached_at": time.monotonic(), "payload": normalized}
            result = dict(normalized)
            result["cache_status"] = "live"
            result["cache_age_seconds"] = 0
            return result
        except WeatherServiceError:
            if cached and now - cached["cached_at"] <= stale_limit_seconds:
                result = dict(cached["payload"])
                result["cache_status"] = "stale"
                result["cache_age_seconds"] = int(now - cached["cached_at"])
                result["stale_data_warning"] = (
                    "The weather provider is unavailable. This is cached forecast data; "
                    "check its timestamp and do not treat it as current conditions."
                )
                return result
            raise
