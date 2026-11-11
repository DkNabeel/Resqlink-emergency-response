import unittest

from app.services.traffic_service import TrafficServiceError, normalize_route_response
from app.services.facility_discovery_service import normalize_overpass_elements


class TrafficTests(unittest.TestCase):
    def test_normalizes_road_eta_and_distance(self):
        result = normalize_route_response({
            "routes": [{
                "summary": {"duration": 900, "distance": 12500},
                "geometry": "abc123",
            }]
        })
        self.assertEqual(result["estimated_travel_time_minutes"], 15)
        self.assertFalse(result["live_traffic_available"])
        self.assertEqual(result["distance_km"], 12.5)

    def test_traffic_route_sends_departure_time_now(self):
        import asyncio
        import os
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.traffic_service import get_traffic_route

        response = MagicMock()
        response.json.return_value = {
            "routes": [{
                "summary": {"duration": 600, "distance": 5000},
                "geometry": "xyz",
            }]
        }
        response.raise_for_status = MagicMock()

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return None
            async def post(self, url, json, headers):
                self.url, self.body, self.headers = url, json, headers
                return response

        fake = FakeClient()
        with patch.dict(os.environ, {"OPENROUTESERVICE_API_KEY": "test-key"}):
            with patch("app.services.traffic_service.httpx.AsyncClient", return_value=fake):
                result = asyncio.run(get_traffic_route(12.9, 77.5, 12.91, 77.51))

        self.assertEqual(fake.url, "https://api.heigit.org/openrouteservice/v2/directions/driving-car")
        self.assertEqual(fake.body["coordinates"], [[77.5, 12.9], [77.51, 12.91]])
        self.assertEqual(fake.headers["Authorization"], "test-key")
        self.assertEqual(result["estimated_travel_time_minutes"], 10)
        self.assertFalse(result["live_traffic_available"])

    def test_empty_route_response_is_rejected(self):
        with self.assertRaises(TrafficServiceError):
            normalize_route_response({"routes": []})


class FacilityDiscoveryTests(unittest.TestCase):
    def test_nodes_and_way_centers_become_unverified_facilities(self):
        result = normalize_overpass_elements([
            {
                "type": "node", "id": 1, "lat": 12.9, "lon": 77.5,
                "tags": {"name": "City Hospital", "amenity": "hospital", "phone": "100"},
            },
            {
                "type": "way", "id": 2, "center": {"lat": 12.91, "lon": 77.51},
                "tags": {"name": "Fire Station", "amenity": "fire_station"},
            },
        ], 12.9, 77.5, 5)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["verification_status"], "unverified")
        self.assertIn("distance_km", result[0])

    def test_unclassified_or_out_of_radius_places_are_excluded(self):
        result = normalize_overpass_elements([
            {"type": "node", "id": 1, "lat": 12.9, "lon": 77.5, "tags": {"amenity": "school"}},
            {"type": "node", "id": 2, "lat": 13.9, "lon": 77.5, "tags": {"name": "Far Hospital", "amenity": "hospital"}},
        ], 12.9, 77.5, 2)
        self.assertEqual(result, [])

    def test_keeps_unnamed_facilities_with_address_or_osm_id(self):
        result = normalize_overpass_elements([
            {
                "type": "way", "id": 246514894,
                "center": {"lat": 12.765146, "lon": 75.207966},
                "tags": {
                    "amenity": "hospital",
                    "addr:district": "Dakshina Kannada",
                    "addr:full": "A.P.M.C. Road, Puttur",
                },
            },
            {
                "type": "node", "id": 69387696, "lat": 12.75854, "lon": 75.196183,
                "tags": {"amenity": "hospital"},
            },
            {
                "type": "node", "id": 42, "lat": 12.76, "lon": 75.20,
                "tags": {"amenity": "shelter"},
            },
        ], 12.795665856, 75.209681191, 10)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["name"], "Hospital near A.P.M.C. Road, Puttur")
        self.assertEqual(result[0]["osm_name"], None)
        self.assertFalse(result[0]["has_map_name"])
        self.assertEqual(result[0]["osm_id"], 246514894)
        self.assertEqual(result[0]["verification_status"], "unverified")
        self.assertIn("OSM node/69387696", result[1]["name"])
        self.assertTrue(result[2]["name"].startswith("Unnamed Shelter"))

    def test_deduplicates_same_place(self):
        place = {"type": "node", "id": 1, "lat": 12.9, "lon": 77.5,
                 "tags": {"name": "Clinic", "healthcare": "clinic"}}
        self.assertEqual(
            len(normalize_overpass_elements([place, place], 12.9, 77.5, 5)),
            1,
        )

    def test_fails_over_to_another_overpass_instance_after_http_502(self):
        import asyncio
        from unittest.mock import patch
        import httpx
        from app.services import facility_discovery_service as service

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"elements": []}

        class FakeClient:
            def __init__(self):
                self.urls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, data, timeout=None):
                self.urls.append(url)
                self.timeouts = getattr(self, "timeouts", [])
                self.timeouts.append(timeout)
                if len(self.urls) == 1:
                    request = httpx.Request("POST", url)
                    response = httpx.Response(502, request=request)
                    raise httpx.HTTPStatusError(
                        "Overpass temporarily unavailable",
                        request=request,
                        response=response,
                    )
                return FakeResponse()

        fake = FakeClient()
        service.clear_discovery_cache()
        try:
            with patch("app.services.facility_discovery_service.httpx.AsyncClient", return_value=fake):
                result = asyncio.run(service.discover_facilities(12.9, 77.5, 5))
        finally:
            service.clear_discovery_cache()

        self.assertEqual(fake.urls, list(service.OVERPASS_URLS[:2]))
        self.assertEqual(fake.timeouts[0].read, 35.0)
        self.assertEqual(fake.timeouts[1].read, 12.0)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["cache_status"], "live")


if __name__ == "__main__":
    unittest.main()
