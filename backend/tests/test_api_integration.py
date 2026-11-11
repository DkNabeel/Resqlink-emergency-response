import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.database.connection as database_connection
from app.main import app
from app.database.init_db import create_tables
from app.database.facility_repository import get_all_facilities


class ResQLinkApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_database_path = database_connection.DATABASE_PATH
        cls.temp_dir = tempfile.TemporaryDirectory()
        database_connection.DATABASE_PATH = Path(cls.temp_dir.name) / "api-test.sqlite3"

        cls.old_sync_enabled = os.environ.get("SACHET_SYNC_ENABLED")
        cls.old_admin_token = os.environ.get("FACILITY_ADMIN_TOKEN")
        os.environ["SACHET_SYNC_ENABLED"] = "false"
        os.environ["FACILITY_ADMIN_TOKEN"] = "integration-test-admin-secret"

        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        database_connection.DATABASE_PATH = cls.original_database_path
        if cls.old_sync_enabled is None:
            os.environ.pop("SACHET_SYNC_ENABLED", None)
        else:
            os.environ["SACHET_SYNC_ENABLED"] = cls.old_sync_enabled
        if cls.old_admin_token is None:
            os.environ.pop("FACILITY_ADMIN_TOKEN", None)
        else:
            os.environ["FACILITY_ADMIN_TOKEN"] = cls.old_admin_token
        cls.temp_dir.cleanup()

    def setUp(self):
        connection = database_connection.get_connection()
        try:
            connection.execute("DELETE FROM facilities")
            connection.execute("DELETE FROM alerts")
            connection.execute("DELETE FROM location_history")
            connection.commit()
        finally:
            connection.close()

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_emergency_endpoint_returns_localized_guidance_and_112(self):
        response = self.client.post(
            "/emergency",
            json={
                "message": "ಭೂಕಂಪ ಆಗುತ್ತಿದೆ, ನೆಲ ನಡುಗುತ್ತಿದೆ",
                "language": "kn",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["emergency_type"], "earthquake")
        self.assertEqual(body["language"], "kn")
        self.assertEqual(body["emergency_contact"]["number"], "112")
        self.assertTrue(body["guidance"])

    def test_emergency_rejects_partial_coordinates(self):
        response = self.client.post(
            "/emergency",
            json={"message": "There is a fire", "latitude": 12.9},
        )
        self.assertEqual(response.status_code, 422)

    def test_facility_lifecycle_and_verification(self):
        created = self.client.post(
            "/facilities",
            json={
                "name": "Test District Hospital",
                "facility_type": "hospital",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "address": "Test address",
                "source_name": "Demo fixture; not a real facility",
            },
        )
        self.assertEqual(created.status_code, 201)
        facility_id = created.json()["facility_id"]

        nearby = self.client.get(
            "/facilities/nearby",
            params={
                "latitude": 12.9716,
                "longitude": 77.5946,
                "radius_km": 2,
                "facility_type": "hospital",
            },
        )
        self.assertEqual(nearby.status_code, 200)
        self.assertEqual(nearby.json()["count"], 1)
        self.assertEqual(nearby.json()["items"][0]["distance_km"], 0)
        self.assertEqual(nearby.json()["items"][0]["verification_status"], "unverified")

        no_token = self.client.post(
            f"/facilities/{facility_id}/verification",
            json={
                "verification_status": "verified",
                "verification_note": "Checked source directory",
            },
        )
        self.assertEqual(no_token.status_code, 403)

        verified = self.client.post(
            f"/facilities/{facility_id}/verification",
            headers={"X-Admin-Token": "integration-test-admin-secret"},
            json={
                "verification_status": "verified",
                "verification_note": "Checked against the official district directory.",
            },
        )
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.json()["verification_status"], "verified")

        verified_only = self.client.get(
            "/facilities",
            params={"verification_status": "verified"},
        )
        self.assertEqual(verified_only.json()["count"], 1)

        updated = self.client.put(
            f"/facilities/{facility_id}",
            json={
                "name": "Updated Test Hospital",
                "facility_type": "hospital",
                "latitude": 12.972,
                "longitude": 77.595,
                "address": "Updated test address",
            },
        )
        self.assertEqual(updated.status_code, 200)

        after_update = self.client.get("/facilities").json()["items"][0]
        self.assertEqual(after_update["verification_status"], "unverified")

        deleted = self.client.delete(f"/facilities/{facility_id}")
        self.assertEqual(deleted.status_code, 200)
        missing = self.client.delete(f"/facilities/{facility_id}")
        self.assertEqual(missing.status_code, 404)

    def test_system_status_is_transparent_about_unimplemented_mobile_and_gemini(self):
        response = self.client.get("/system/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["providers"]["gemini"]["endpoint_connected"])
        self.assertEqual(body["mobile"]["on_device_offline_cache"], "not_implemented")
        self.assertEqual(body["providers"]["weather"]["provider"], "Open-Meteo")

    def test_blank_inputs_are_rejected(self):
        emergency = self.client.post("/emergency", json={"message": "   "})
        self.assertEqual(emergency.status_code, 422)

        facility = self.client.post(
            "/facilities",
            json={
                "name": "   ",
                "facility_type": "hospital",
                "latitude": 12.9,
                "longitude": 77.5,
            },
        )
        self.assertEqual(facility.status_code, 422)

    def test_emergency_returns_only_relevant_facility_types(self):
        self.client.post(
            "/facilities",
            json={
                "name": "Demo Hospital",
                "facility_type": "hospital",
                "latitude": 12.9716,
                "longitude": 77.5946,
            },
        )
        self.client.post(
            "/facilities",
            json={
                "name": "Demo Fire Station",
                "facility_type": "fire_station",
                "latitude": 12.9717,
                "longitude": 77.5947,
            },
        )
        response = self.client.post(
            "/emergency",
            json={
                "message": "Someone is unconscious",
                "language": "en",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "radius_km": 2,
            },
        )
        self.assertEqual(response.status_code, 200)
        returned_types = {item["facility_type"] for item in response.json()["nearby_facilities"]}
        self.assertEqual(returned_types, {"hospital"})

    def test_legacy_facility_database_migration_preserves_records(self):
        original_path = database_connection.DATABASE_PATH
        with tempfile.TemporaryDirectory() as folder:
            legacy_path = Path(folder) / "legacy.sqlite3"
            database_connection.DATABASE_PATH = legacy_path
            connection = sqlite3.connect(legacy_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE facilities (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        facility_type TEXT NOT NULL,
                        latitude REAL NOT NULL,
                        longitude REAL NOT NULL,
                        address TEXT,
                        phone TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO facilities
                        (name, facility_type, latitude, longitude, address, phone)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("Legacy Clinic", "hospital", 12.9, 77.5, "Legacy address", "000"),
                )
                connection.commit()
            finally:
                connection.close()

            try:
                create_tables()
                records = get_all_facilities()
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["name"], "Legacy Clinic")
                self.assertEqual(records[0]["verification_status"], "unverified")
            finally:
                database_connection.DATABASE_PATH = original_path

    def test_offline_package_includes_localized_guidance_and_only_verified_facilities(self):
        verified = self.client.post(
            "/facilities",
            json={
                "name": "Verified Demo Hospital",
                "facility_type": "hospital",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "source_name": "Official directory test fixture",
            },
        )
        verified_id = verified.json()["facility_id"]
        self.client.post(
            f"/facilities/{verified_id}/verification",
            headers={"X-Admin-Token": "integration-test-admin-secret"},
            json={
                "verification_status": "verified",
                "verification_note": "Test fixture only; official directory reviewed.",
            },
        )

        self.client.post(
            "/facilities",
            json={
                "name": "Unverified Demo Clinic",
                "facility_type": "hospital",
                "latitude": 12.9717,
                "longitude": 77.5947,
            },
        )

        response = self.client.get(
            "/offline/package",
            params={
                "latitude": 12.9716,
                "longitude": 77.5946,
                "language": "hi",
                "radius_km": 2,
                "city": "Test City",
            },
        )
        self.assertEqual(response.status_code, 200)
        package = response.json()
        self.assertEqual(package["package_type"], "resqlink_offline_emergency_package")
        self.assertEqual(package["language"], "hi")
        self.assertEqual(package["emergency_contact"]["number"], "112")
        self.assertIn("fire", package["guidance_catalog"])
        self.assertIn("instructions", package["guidance_catalog"]["fire"])
        self.assertEqual(len(package["nearby_verified_facilities"]), 1)
        self.assertEqual(
            package["nearby_verified_facilities"][0]["verification_status"],
            "verified",
        )
        self.assertFalse(package["offline_capabilities"]["map_tiles_included"])
        self.assertFalse(package["offline_capabilities"]["live_alert_updates"])

    def test_location_save_and_last_known(self):
        saved = self.client.post(
            "/locations/resolve",
            json={
                "device_id": "resqlink-test-device",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "source": "gps",
                "accuracy_m": 15,
                "city": "Test City",
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["location_available"])
        self.assertTrue(saved.json()["location_is_current"])

        retrieved = self.client.get(
            "/locations/resqlink-test-device/last-known"
        )
        self.assertEqual(retrieved.status_code, 200)
        self.assertEqual(retrieved.json()["latitude"], 12.9716)

    def test_weather_endpoint_can_return_provider_data(self):
        async def fake_weather(latitude, longitude, forecast_hours):
            return {
                "latitude": latitude,
                "longitude": longitude,
                "forecast_hours": [],
                "source": "Open-Meteo",
                "cache_status": "live",
            }

        from unittest.mock import patch
        with patch("app.main.get_weather_snapshot", side_effect=fake_weather):
            response = self.client.get(
                "/weather/nearby",
                params={"latitude": 12.97, "longitude": 77.59, "forecast_hours": 6},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "Open-Meteo")
        self.assertEqual(response.json()["cache_status"], "live")


if __name__ == "__main__":
    unittest.main()
