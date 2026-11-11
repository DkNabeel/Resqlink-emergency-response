import unittest

from app.services.traffic_service import TrafficServiceError, normalize_route_response
from app.services.facility_discovery_service import normalize_overpass_elements


class TrafficTests(unittest.TestCase):
    def test_normalizes_traffic_eta_and_distance(self):
        result = normalize_route_response({
            "routes": [{
                "duration": "900s",
                "staticDuration": "720s",
                "distanceMeters": 12500,
                "polyline": {"encodedPolyline": "abc123"},
            }]
        })
        self.assertEqual(result["traffic_aware_eta_minutes"], 15)
        self.assertEqual(result["estimated_traffic_delay_minutes"], 3)
        self.assertEqual(result["distance_km"], 12.5)

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

    def test_unnamed_or_out_of_radius_places_are_excluded(self):
        result = normalize_overpass_elements([
            {"type": "node", "id": 1, "lat": 12.9, "lon": 77.5, "tags": {"amenity": "hospital"}},
            {"type": "node", "id": 2, "lat": 13.9, "lon": 77.5, "tags": {"name": "Far Hospital", "amenity": "hospital"}},
        ], 12.9, 77.5, 2)
        self.assertEqual(result, [])

    def test_deduplicates_same_place(self):
        place = {"type": "node", "id": 1, "lat": 12.9, "lon": 77.5,
                 "tags": {"name": "Clinic", "healthcare": "clinic"}}
        self.assertEqual(
            len(normalize_overpass_elements([place, place], 12.9, 77.5, 5)),
            1,
        )


if __name__ == "__main__":
    unittest.main()
