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

    def test_normalizes_geojson_route_geometry_for_mobile_preview(self):
        result = normalize_route_response({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.5, 12.9], [77.51, 12.91]],
                },
                "properties": {
                    "summary": {"duration": 600, "distance": 5000},
                },
            }],
        })
        self.assertEqual(result["estimated_travel_time_minutes"], 10)
        self.assertEqual(result["route_geometry"]["type"], "LineString")
        self.assertEqual(result["route_geometry"]["coordinates"][0], [77.5, 12.9])

    def test_traffic_route_sends_departure_time_now(self):
        import asyncio
        import os
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.traffic_service import get_traffic_route

        response = MagicMock()
        response.json.return_value = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.5, 12.9], [77.51, 12.91]],
                },
                "properties": {
                    "summary": {"duration": 600, "distance": 5000},
                },
            }],
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

        self.assertEqual(fake.url, "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson")
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

    def test_college_school_clinic_pharmacy_and_community_centres_are_included(self):
        result = normalize_overpass_elements([
            {"type": "node", "id": 10, "lat": 12.9, "lon": 77.5, "tags": {"amenity": "college"}},
            {"type": "node", "id": 11, "lat": 12.901, "lon": 77.501, "tags": {"building": "school"}},
            {"type": "node", "id": 12, "lat": 12.902, "lon": 77.502, "tags": {"healthcare": "clinic"}},
            {"type": "node", "id": 13, "lat": 12.903, "lon": 77.503, "tags": {"amenity": "pharmacy"}},
            {"type": "node", "id": 14, "lat": 12.904, "lon": 77.504, "tags": {"amenity": "community_centre"}},
            {"type": "node", "id": 15, "lat": 12.905, "lon": 77.505, "tags": {"amenity": "police"}},
            {"type": "node", "id": 16, "lat": 12.906, "lon": 77.506, "tags": {"amenity": "fire_station"}},
        ], 12.9, 77.5, 5)
        by_id = {item["osm_id"]: item["facility_type"] for item in result}
        self.assertEqual(by_id, {
            10: "education",
            11: "education",
            12: "clinic",
            13: "pharmacy",
            14: "community_center",
            15: "police",
            16: "fire_station",
        })

    def test_additional_healthcare_and_emergency_tags_are_recognized(self):
        result = normalize_overpass_elements([
            {
                "type": "node", "id": 101, "lat": 12.9, "lon": 77.5,
                "tags": {"amenity": "healthcare", "name": "Local Health Centre"},
            },
            {
                "type": "node", "id": 102, "lat": 12.901, "lon": 77.501,
                "tags": {"healthcare": "centre", "name": "Rural Health Centre"},
            },
            {
                "type": "node", "id": 103, "lat": 12.902, "lon": 77.502,
                "tags": {"emergency": "shelter", "name": "Community Emergency Shelter"},
            },
        ], 12.9, 77.5, 5)
        by_id = {item["osm_id"]: item["facility_type"] for item in result}
        self.assertEqual(by_id, {
            101: "clinic",
            102: "clinic",
            103: "shelter",
        })

    def test_unclassified_or_out_of_radius_places_are_excluded(self):
        result = normalize_overpass_elements([
            {"type": "node", "id": 1, "lat": 12.9, "lon": 77.5, "tags": {"amenity": "restaurant"}},
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
        by_osm_id = {item["osm_id"]: item for item in result}
        self.assertEqual(by_osm_id[246514894]["name"], "Hospital near A.P.M.C. Road, Puttur")
        self.assertEqual(by_osm_id[246514894]["osm_name"], None)
        self.assertFalse(by_osm_id[246514894]["has_map_name"])
        self.assertEqual(by_osm_id[246514894]["verification_status"], "unverified")
        self.assertIn("OSM node/69387696", by_osm_id[69387696]["name"])
        self.assertTrue(by_osm_id[42]["name"].startswith("Unnamed Shelter"))

    def test_deduplicates_same_place(self):
        place = {"type": "node", "id": 1, "lat": 12.9, "lon": 77.5,
                 "tags": {"name": "Clinic", "healthcare": "clinic"}}
        self.assertEqual(
            len(normalize_overpass_elements([place, place], 12.9, 77.5, 5)),
            1,
        )

    def test_same_named_point_and_building_outline_are_deduplicated(self):
        items = normalize_overpass_elements([
            {
                "type": "node", "id": 200, "lat": 12.9000, "lon": 77.5000,
                "tags": {"name": "District Hospital", "amenity": "hospital"},
            },
            {
                "type": "way", "id": 201,
                "center": {"lat": 12.9005, "lon": 77.5000},
                "tags": {
                    "name": "District Hospital",
                    "amenity": "hospital",
                    "phone": "0824-000000",
                    "addr:full": "Main Road",
                },
            },
        ], 12.9, 77.5, 5)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["osm_id"], 201)
        self.assertEqual(items[0]["phone"], "0824-000000")
        self.assertEqual(items[0]["address"], "Main Road")

    def test_keeps_different_nearby_facilities_even_when_coordinates_are_close(self):
        items = normalize_overpass_elements([
            {
                "type": "node", "id": 210, "lat": 12.9000, "lon": 77.5000,
                "tags": {"name": "District Hospital", "amenity": "hospital"},
            },
            {
                "type": "node", "id": 211, "lat": 12.9001, "lon": 77.5000,
                "tags": {"name": "City Hospital", "amenity": "hospital"},
            },
        ], 12.9, 77.5, 5)

        self.assertEqual(len(items), 2)

    def test_returns_metre_precision_straight_line_distance(self):
        items = normalize_overpass_elements([
            {
                "type": "node", "id": 220, "lat": 12.9010, "lon": 77.5000,
                "tags": {"name": "Nearby Hospital", "amenity": "hospital"},
            },
        ], 12.9, 77.5, 5)

        self.assertEqual(len(items), 1)
        self.assertGreater(items[0]["distance_meters"], 0)
        self.assertEqual(items[0]["distance_kind"], "straight_line")
        self.assertEqual(
            items[0]["distance_km"],
            round(items[0]["distance_meters"] / 1000, 2),
        )


    def test_fails_over_when_first_overpass_instance_returns_empty_snapshot(self):
        import asyncio
        from unittest.mock import patch
        from app.services import facility_discovery_service as service

        class FakeResponse:
            def __init__(self, elements):
                self.elements = elements
            def raise_for_status(self):
                return None
            def json(self):
                return {"elements": self.elements}

        class FakeClient:
            def __init__(self):
                self.urls = []
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return None
            async def post(self, url, data, timeout=None):
                self.urls.append(url)
                if len(self.urls) == 1:
                    return FakeResponse([])
                return FakeResponse([{
                    "type": "node", "id": 99, "lat": 12.9, "lon": 77.5,
                    "tags": {"amenity": "hospital", "name": "Fallback Hospital"},
                }])

        fake = FakeClient()
        service.clear_discovery_cache()
        try:
            with patch("app.services.facility_discovery_service.httpx.AsyncClient", return_value=fake):
                result = asyncio.run(service.discover_facilities(12.9, 77.5, 5))
        finally:
            service.clear_discovery_cache()

        self.assertEqual(fake.urls, list(service.OVERPASS_URLS[:2]))
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "Fallback Hospital")
        self.assertEqual(result["provider_endpoint"], service.OVERPASS_URLS[1])

    def test_regionally_limited_swiss_endpoint_is_not_used_for_indian_search(self):
        from app.services import facility_discovery_service as service

        self.assertTrue(service.OVERPASS_URLS)
        self.assertNotIn("https://overpass.osm.ch/api/interpreter", service.OVERPASS_URLS)
        self.assertIn("https://overpass.private.coffee/api/interpreter", service.OVERPASS_URLS)

    def test_http_200_overpass_remark_triggers_global_failover(self):
        import asyncio
        from unittest.mock import patch
        from app.services import facility_discovery_service as service

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.urls = []
                self.query = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, data, timeout=None):
                self.urls.append(url)
                self.query = data["data"]
                if len(self.urls) == 1:
                    # Overpass may signal timeout in a JSON remark despite HTTP 200.
                    return FakeResponse({
                        "remark": 'runtime error: Query timed out in "query" at line 2',
                        "elements": [],
                    })
                return FakeResponse({"elements": [{
                    "type": "node", "id": 501, "lat": 12.9, "lon": 77.5,
                    "tags": {"amenity": "hospital", "name": "Fallback Hospital"},
                }]})

        fake = FakeClient()
        service.clear_discovery_cache()
        try:
            with patch("app.services.facility_discovery_service.httpx.AsyncClient", return_value=fake):
                result = asyncio.run(service.discover_facilities(12.9, 77.5, 5))
        finally:
            service.clear_discovery_cache()

        self.assertEqual(fake.urls, list(service.OVERPASS_URLS[:2]))
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "Fallback Hospital")
        self.assertNotIn("(around:", fake.query)
        self.assertIn("12.855", fake.query)
        self.assertIn("77.453921", fake.query)
        self.assertTrue(fake.query.startswith("[out:json][timeout:30];"))

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

        self.assertEqual(fake.urls, list(service.OVERPASS_URLS))
        self.assertEqual(fake.timeouts[0].read, 38.0)
        self.assertTrue(all(item.read == 20.0 for item in fake.timeouts[1:]))
        self.assertEqual(result["items"], [])
        self.assertEqual(result["raw_element_count"], 0)
        self.assertEqual(result["cache_status"], "live")


if __name__ == "__main__":
    unittest.main()
