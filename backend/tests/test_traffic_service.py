import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from app.services import traffic_service


SAMPLE_ORS_RESPONSE = {
    "routes": [
        {
            "summary": {"distance": 4275.4, "duration": 623.2},
            "geometry": "encoded-route-polyline",
        }
    ]
}


class OpenRouteServiceNormalizationTests(unittest.TestCase):
    def test_normalizes_road_distance_duration_and_geometry(self):
        result = traffic_service.normalize_route_response(SAMPLE_ORS_RESPONSE)

        self.assertEqual(result["provider"], "OpenRouteService (HeiGIT)")
        self.assertEqual(result["travel_mode"], "DRIVE")
        self.assertFalse(result["live_traffic_available"])
        self.assertEqual(result["estimated_travel_time_seconds"], 623)
        self.assertEqual(result["estimated_travel_time_minutes"], 10.4)
        self.assertEqual(result["distance_meters"], 4275)
        self.assertEqual(result["distance_km"], 4.28)
        self.assertEqual(result["encoded_polyline"], "encoded-route-polyline")
        self.assertIn("not included", result["note"])

    def test_rejects_missing_route(self):
        with self.assertRaises(traffic_service.TrafficServiceError):
            traffic_service.normalize_route_response({"routes": []})

    def test_rejects_invalid_summary(self):
        with self.assertRaises(traffic_service.TrafficServiceError):
            traffic_service.normalize_route_response(
                {"routes": [{"summary": {"distance": "far", "duration": 100}}]}
            )


class OpenRouteServiceRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_lon_lat_order_and_server_side_api_key(self):
        response = Mock()
        response.json.return_value = SAMPLE_ORS_RESPONSE
        response.raise_for_status.return_value = None

        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client.post.return_value = response

        with (
            patch.dict(
                os.environ,
                {"OPENROUTESERVICE_API_KEY": "test-secret"},
                clear=True,
            ),
            patch.object(
                traffic_service.httpx,
                "AsyncClient",
                return_value=client,
            ),
        ):
            result = await traffic_service.get_traffic_route(
                12.9716, 77.5946, 12.9352, 77.6245
            )

        self.assertEqual(result["provider"], "OpenRouteService (HeiGIT)")
        call = client.post.await_args
        self.assertEqual(
            call.args[0],
            "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson",
        )
        self.assertEqual(call.kwargs["headers"]["Authorization"], "test-secret")
        self.assertEqual(
            call.kwargs["json"]["coordinates"],
            [[77.5946, 12.9716], [77.6245, 12.9352]],
        )

    async def test_bearer_prefix_is_removed_from_heigit_authorization_header(self):
        response = Mock()
        response.json.return_value = SAMPLE_ORS_RESPONSE
        response.raise_for_status.return_value = None

        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client.post.return_value = response

        with (
            patch.dict(
                os.environ,
                {"OPENROUTESERVICE_API_KEY": "Bearer full-test-secret"},
                clear=True,
            ),
            patch.object(traffic_service.httpx, "AsyncClient", return_value=client),
        ):
            await traffic_service.get_traffic_route(
                12.9716, 77.5946, 12.9352, 77.6245
            )

        self.assertEqual(
            client.post.await_args.kwargs["headers"]["Authorization"],
            "full-test-secret",
        )

    async def test_403_includes_provider_message_and_key_recovery_guidance(self):
        request = httpx.Request(
            "POST",
            "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson",
        )
        response = httpx.Response(
            403,
            request=request,
            json={"error": {"code": 403, "message": "Access to this API has been disallowed"}},
        )

        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client.post.return_value = response

        with (
            patch.dict(
                os.environ,
                {"OPENROUTESERVICE_API_KEY": "full-test-secret"},
                clear=True,
            ),
            patch.object(traffic_service.httpx, "AsyncClient", return_value=client),
        ):
            with self.assertRaises(traffic_service.TrafficServiceError) as raised:
                await traffic_service.get_traffic_route(
                    12.9716, 77.5946, 12.9352, 77.6245
                )

        message = str(raised.exception)
        self.assertIn("HTTP 403", message)
        self.assertIn("Access to this API has been disallowed", message)
        self.assertIn("account.heigit.org", message)
        self.assertNotIn("full-test-secret", message)

    async def test_missing_key_is_reported_without_network_call(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(traffic_service.TrafficNotConfigured):
                await traffic_service.get_traffic_route(
                    12.9716, 77.5946, 12.9352, 77.6245
                )

    async def test_rejects_invalid_coordinates_before_network_call(self):
        with patch.dict(
            os.environ,
            {"OPENROUTESERVICE_API_KEY": "test-secret"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                await traffic_service.get_traffic_route(
                    92, 77.5946, 12.9352, 77.6245
                )


class OpenRouteServiceMatrixTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        traffic_service.clear_traffic_matrix_cache()

    def tearDown(self):
        traffic_service.clear_traffic_matrix_cache()

    async def test_normalizes_road_distance_and_duration_rows(self):
        result = traffic_service.normalize_matrix_response(
            {
                "distances": [[4275.4, 812.2]],
                "durations": [[623.2, 144.4]],
            },
            expected_destinations=2,
        )

        self.assertEqual(result[0]["road_distance_meters"], 4275)
        self.assertEqual(result[0]["road_distance_km"], 4.28)
        self.assertEqual(result[0]["road_duration_seconds"], 623)
        self.assertEqual(result[0]["road_duration_minutes"], 10.4)
        self.assertEqual(result[0]["road_route_status"], "available")
        self.assertEqual(result[1]["road_distance_meters"], 812)

    def test_marks_unreachable_matrix_destinations(self):
        result = traffic_service.normalize_matrix_response(
            {"distances": [[None]], "durations": [[None]]},
            expected_destinations=1,
        )
        self.assertIsNone(result[0]["road_distance_meters"])
        self.assertEqual(result[0]["road_route_status"], "unreachable")

    async def test_sends_one_batched_request_and_reuses_five_minute_cache(self):
        response = Mock()
        response.json.return_value = {
            "distances": [[4275.4, 812.2]],
            "durations": [[623.2, 144.4]],
        }
        response.raise_for_status.return_value = None

        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client.post.return_value = response

        destinations = [(12.9000, 77.6000), (12.9100, 77.6100)]
        with (
            patch.dict(
                os.environ,
                {"OPENROUTESERVICE_API_KEY": "test-secret"},
                clear=True,
            ),
            patch.object(
                traffic_service.httpx,
                "AsyncClient",
                return_value=client,
            ),
        ):
            live = await traffic_service.get_traffic_matrix(
                12.9716, 77.5946, destinations
            )
            cached = await traffic_service.get_traffic_matrix(
                12.9716, 77.5946, destinations
            )

        self.assertEqual(live["cache_status"], "live")
        self.assertEqual(cached["cache_status"], "cached")
        self.assertEqual(client.post.await_count, 1)

        call = client.post.await_args
        self.assertEqual(
            call.args[0],
            "https://api.heigit.org/openrouteservice/v2/matrix/driving-car",
        )
        self.assertEqual(call.kwargs["headers"]["Authorization"], "test-secret")
        self.assertEqual(
            call.kwargs["json"]["locations"],
            [
                [77.5946, 12.9716],
                [77.6000, 12.9000],
                [77.6100, 12.9100],
            ],
        )
        self.assertEqual(call.kwargs["json"]["sources"], ["0"])
        self.assertEqual(call.kwargs["json"]["destinations"], ["1", "2"])
        self.assertEqual(call.kwargs["json"]["metrics"], ["distance", "duration"])
        self.assertEqual(live["items"][0]["road_distance_meters"], 4275)
        self.assertEqual(cached["items"][1]["road_duration_minutes"], 2.4)

    async def test_deduplicates_identical_destination_coordinates(self):
        response = Mock()
        response.json.return_value = {
            "distances": [[1500]],
            "durations": [[180]],
        }
        response.raise_for_status.return_value = None

        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client.post.return_value = response

        with (
            patch.dict(
                os.environ,
                {"OPENROUTESERVICE_API_KEY": "test-secret"},
                clear=True,
            ),
            patch.object(traffic_service.httpx, "AsyncClient", return_value=client),
        ):
            result = await traffic_service.get_traffic_matrix(
                12.9716,
                77.5946,
                [(12.9000, 77.6000), (12.9000, 77.6000)],
            )

        self.assertEqual(client.post.await_count, 1)
        self.assertEqual(len(client.post.await_args.kwargs["json"]["locations"]), 2)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0], result["items"][1])

    async def test_missing_matrix_key_does_not_make_network_call(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(traffic_service.TrafficNotConfigured):
                await traffic_service.get_traffic_matrix(
                    12.9716, 77.5946, [(12.9000, 77.6000)]
                )

    async def test_rejects_more_than_24_destinations_without_network_call(self):
        with patch.dict(
            os.environ,
            {"OPENROUTESERVICE_API_KEY": "test-secret"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                await traffic_service.get_traffic_matrix(
                    12.9716,
                    77.5946,
                    [(12.9, 77.6 + index * 0.001) for index in range(25)],
                )

if __name__ == "__main__":
    unittest.main()
