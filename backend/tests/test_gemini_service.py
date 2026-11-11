import os
import unittest
from unittest.mock import patch

import httpx

from app.services.ai_service import AIServiceError, analyze_emergency_with_groq, parse_classification


class GroqClassificationTests(unittest.TestCase):
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
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
            with self.assertRaises(AIServiceError):
                analyze_emergency_with_groq("There is a fire")

    def test_primary_503_uses_fallback_model(self):
        success = httpx.Response(
            200,
            json={"choices": [{"message": {"content":
                '{"emergency_type":"fire","confidence":"medium",'
                '"short_summary":"Fire report","key_details":["Smoke"]}'
            }}]},
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )
        unavailable = httpx.Response(
            503,
            text="Model temporarily unavailable",
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "test-key",
            "GROQ_MODEL": "primary-model",
            "GROQ_FALLBACK_MODEL": "fallback-model",
        }):
            with patch("app.services.ai_service.httpx.post", side_effect=[unavailable, success]) as post:
                result = analyze_emergency_with_groq("Smoke reported", "en", "unknown")
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["provider"], "Groq API")
        self.assertEqual(result["model"], "fallback-model")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "fallback-model")
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], {"type": "json_object"})

    def test_provider_key_is_only_sent_in_authorization_header(self):
        success = httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"emergency_type":"unknown"}'}}]},
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "test-secret",
            "GROQ_MODEL": "primary-model",
            "GROQ_FALLBACK_MODEL": "primary-model",
        }):
            with patch("app.services.ai_service.httpx.post", return_value=success) as post:
                analyze_emergency_with_groq("Help", "en", "unknown")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-secret")
        self.assertNotIn("test-secret", str(post.call_args.kwargs["json"]))


if __name__ == "__main__":
    unittest.main()
