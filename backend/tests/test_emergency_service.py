import unittest

from app.services.emergency_service import build_emergency_response, detect_emergency


class EmergencyIntentTests(unittest.TestCase):
    def test_fire_english(self):
        self.assertEqual(detect_emergency("There is smoke and fire")["emergency_type"], "fire")

    def test_flood_hindi(self):
        self.assertEqual(detect_emergency("मेरे घर में बाढ़ का पानी भर रहा है")["emergency_type"], "flood")

    def test_earthquake_kannada(self):
        self.assertEqual(detect_emergency("ಭೂಕಂಪ ಆಗುತ್ತಿದೆ, ನೆಲ ನಡುಗುತ್ತಿದೆ")["emergency_type"], "earthquake")

    def test_localized_medical_guidance(self):
        result = build_emergency_response("Person is unconscious", "kn")
        self.assertEqual(result["emergency_type"], "medical")
        self.assertEqual(result["language"], "kn")
        self.assertGreaterEqual(len(result["guidance"]), 3)

    def test_unknown_fallback(self):
        result = build_emergency_response("Please help me", "en")
        self.assertEqual(result["emergency_type"], "unknown")
        self.assertTrue(result["guidance"])

    def test_gas_leak_detected(self):
        result = build_emergency_response("I smell a gas leak", "en")
        self.assertEqual(result["emergency_type"], "gas_leak")
        self.assertIn("fire_station", result["recommended_facility_types"])

    def test_cyclone_detected_in_hindi(self):
        result = build_emergency_response("चक्रवात आने वाला है", "hi")
        self.assertEqual(result["emergency_type"], "cyclone")
        self.assertEqual(result["language"], "hi")

    def test_landslide_detected_in_kannada(self):
        result = build_emergency_response("ಬೆಟ್ಟ ಕುಸಿತ ಆಗುತ್ತಿದೆ", "kn")
        self.assertEqual(result["emergency_type"], "landslide")
        self.assertIn("shelter", result["recommended_facility_types"])

    def test_multiple_emergency_types_are_reported(self):
        result = detect_emergency("There is a fire after an earthquake")
        self.assertEqual(result["emergency_type"], "fire")
        self.assertTrue(result["multiple_emergency_types_detected"])
        self.assertIn("earthquake", result["all_detected_types"])

        response = build_emergency_response(
            "There is a fire after an earthquake", "en"
        )
        self.assertIn("fire", response["guidance_by_emergency_type"])
        self.assertIn("earthquake", response["guidance_by_emergency_type"])
        self.assertTrue(any("shaking" in item.lower() for item in response["guidance"]))
        self.assertIn("fire_station", response["recommended_facility_types"])
        self.assertIn("shelter", response["recommended_facility_types"])

    def test_india_emergency_number_is_included(self):
        result = build_emergency_response("Someone is unconscious", "en")
        self.assertEqual(result["emergency_contact"]["number"], "112")
        self.assertEqual(result["emergency_contact"]["dial_uri"], "tel:112")


if __name__ == "__main__":
    unittest.main()
