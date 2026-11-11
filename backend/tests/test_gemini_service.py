import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.gemini_service import (
    GeminiServiceError,
    analyze_emergency_with_gemini,
    parse_classification,
)


class GeminiClassificationTests(unittest.TestCase):
    def test_parses_valid_classification(self):
        result = parse_classification(
            '{"emergency_type":"fire","confidence":"high","short_summary":"Smoke reported","key_details":["Smoke"]}'
        )
        self.assertEqual(result["emergency_type"], "fire")
        self.assertEqual(result["confidence"], "high")

    def test_unknown_category_is_safely_normalized(self):
        result = parse_classification('{"emergency_type":"made_up","confidence":"high"}')
        self.assertEqual(result["emergency_type"], "unknown")

    def test_missing_key_fails_without_network(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            with self.assertRaises(GeminiServiceError):
                analyze_emergency_with_gemini("There is a fire")

    def test_generate_content_returns_validated_result(self):
        response = MagicMock()
        response.text = (
            '{"emergency_type":"gas_leak","confidence":"high",'
            '"short_summary":"Possible gas leak","key_details":["Smell of gas"]}'
        )
        client = MagicMock()
        client.models.generate_content.return_value = response
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "gemini-test-model",
            "GEMINI_FALLBACK_MODEL": "gemini-test-model",
        }):
            with patch("app.services.gemini_service.genai.Client", return_value=client):
                result = analyze_emergency_with_gemini("I smell gas", "en", "unknown")
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["emergency_type"], "gas_leak")
        client.models.generate_content.assert_called_once()
        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
