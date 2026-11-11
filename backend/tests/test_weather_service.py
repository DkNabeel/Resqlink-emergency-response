import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services import weather_service


SAMPLE_WEATHER = {
    "latitude": 12.97,
    "longitude": 77.59,
    "timezone": "Asia/Kolkata",
    "current": {
        "time": "2026-11-11T11:00",
        "temperature_2m": 29.0,
        "apparent_temperature": 32.0,
        "relative_humidity_2m": 74,
        "precipitation": 0.2,
        "weather_code": 2,
        "wind_speed_10m": 12.0,
        "wind_gusts_10m": 20.0,
    },
    "hourly": {
        "time": ["2026-11-11T12:00", "2026-11-11T13:00", "2026-11-11T14:00"],
        "precipitation_probability": [10, 55, 80],
        "precipitation": [0.0, 1.2, 8.5],
        "weather_code": [2, 61, 95],
        "wind_speed_10m": [12.0, 15.0, 18.0],
        "wind_gusts_10m": [20.0, 25.0, 30.0],
        "relative_humidity_2m": [70, 75, 80],
    },
}


class WeatherNormalizationTests(unittest.TestCase):
    def test_normalizes_current_and_hourly_weather(self):
        result = weather_service.normalize_weather_payload(
            SAMPLE_WEATHER, 12.97, 77.59, 3
        )
        self.assertEqual(result["current"]["condition"], "Partly cloudy")
        self.assertEqual(len(result["forecast_hours"]), 3)
        self.assertEqual(result["forecast_indicators"]["max_precipitation_probability_pct"], 80)
        self.assertEqual(result["forecast_indicators"]["thunderstorm_forecast_times"], [
            "2026-11-11T14:00"
        ])
        self.assertIn("Open-Meteo", result["attribution"])

    def test_missing_weather_code_is_safe(self):
        result = weather_service.normalize_weather_payload(
            {"hourly": {"time": ["2026-11-11T12:00"]}}, 1, 2, 1
        )
        self.assertEqual(result["forecast_hours"][0]["condition"], "Unknown weather code")


class WeatherCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        weather_service.clear_weather_cache()

    async def asyncTearDown(self):
        weather_service.clear_weather_cache()

    async def test_second_request_uses_short_cache(self):
        fetch = AsyncMock(return_value=SAMPLE_WEATHER)
        with patch.object(weather_service, "_fetch_open_meteo", fetch):
            first = await weather_service.get_weather_snapshot(12.97, 77.59, 3)
            second = await weather_service.get_weather_snapshot(12.97, 77.59, 3)

        self.assertEqual(first["cache_status"], "live")
        self.assertEqual(second["cache_status"], "cached")
        self.assertEqual(fetch.await_count, 1)

    async def test_provider_failure_uses_available_stale_snapshot(self):
        fetch = AsyncMock(return_value=SAMPLE_WEATHER)
        with patch.object(weather_service, "_fetch_open_meteo", fetch):
            await weather_service.get_weather_snapshot(12.97, 77.59, 3)

        with patch.object(
            weather_service,
            "_fetch_open_meteo",
            AsyncMock(side_effect=weather_service.WeatherServiceError("offline")),
        ):
            with patch.object(weather_service, "_CACHE") as cache:
                cache.update(weather_service._CACHE)
                # Force the only entry to be outside fresh TTL but inside stale TTL.
                for item in cache.values():
                    item["cached_at"] -= 700
                with patch.dict("os.environ", {"WEATHER_CACHE_TTL_SECONDS": "600"}):
                    result = await weather_service.get_weather_snapshot(12.97, 77.59, 3)

        self.assertEqual(result["cache_status"], "stale")
        self.assertIn("stale_data_warning", result)


if __name__ == "__main__":
    unittest.main()
