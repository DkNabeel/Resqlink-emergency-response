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


if __name__ == "__main__":
    unittest.main()
