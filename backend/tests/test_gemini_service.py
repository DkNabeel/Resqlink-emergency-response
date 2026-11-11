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

    def test_504_from_primary_tries_one_fallback_model(self):
        response = MagicMock()
        response.text = (
            '{"emergency_type":"fire","confidence":"medium",'
            '"short_summary":"Fire report","key_details":[]}'
        )
        client = MagicMock()
        client.models.generate_content.side_effect = [
            RuntimeError("504 DEADLINE_EXCEEDED"),
            response,
        ]
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "primary-model",
            "GEMINI_FALLBACK_MODEL": "fallback-model",
            "GEMINI_HTTP_TIMEOUT_MS": "5000",
        }):
            with patch("app.services.gemini_service.genai.Client", return_value=client) as client_factory:
                result = analyze_emergency_with_gemini("Smoke reported", "en", "unknown")
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["model"], "fallback-model")
        self.assertEqual(client.models.generate_content.call_count, 2)
        self.assertEqual(
            client.models.generate_content.call_args_list[1].kwargs["model"],
            "fallback-model",
        )
        self.assertGreaterEqual(
            client_factory.call_args.kwargs["http_options"]["timeout"],
            10000,
        )

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
        request_config = client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(request_config.response_mime_type, "application/json")
        self.assertEqual(request_config.max_output_tokens, 300)
        # Gemini 3.8 guidance says to keep sampling parameters at defaults.
        self.assertIsNone(request_config.temperature)
        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
