import os
import unittest
from unittest.mock import patch

import httpx

from app.services.ai_service import (
    AIServiceError,
    analyze_emergency_with_groq,
    parse_classification,
    parse_emergency_chat_response,
    respond_to_emergency_chat,
)


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

    def test_parses_dynamic_emergency_chat_reply(self):
        result = parse_emergency_chat_response(
            '{"in_scope":true,"emergency_type":"earthquake","urgency":"immediate",'
            '"reply":"Move away from damaged structures.","follow_up_question":"Are you outside?"}'
        )
        self.assertTrue(result["in_scope"])
        self.assertEqual(result["emergency_type"], "earthquake")
        self.assertEqual(result["urgency"], "immediate")
        self.assertIn("damaged structures", result["reply"])

    def test_parses_emergency_only_refusal(self):
        result = parse_emergency_chat_response(
            '{"in_scope":false,"emergency_type":"unknown","urgency":"unknown",'
            '"reply":"ResQLink only handles emergencies.","follow_up_question":""}'
        )
        self.assertFalse(result["in_scope"])
        self.assertIsNone(result["follow_up_question"])

    def test_invalid_dynamic_chat_json_is_rejected(self):
        with self.assertRaises(AIServiceError):
            parse_emergency_chat_response("not-json")

    def test_dynamic_groq_chat_sends_emergency_only_prompt_and_history(self):
        success = httpx.Response(
            200,
            json={"choices": [{"message": {"content":
                '{"in_scope":true,"emergency_type":"fire","urgency":"urgent",'
                '"reply":"Leave through a safe exit.","follow_up_question":""}'
            }}]},
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "chat-test-key",
            "GROQ_MODEL": "primary-model",
            "GROQ_FALLBACK_MODEL": "primary-model",
        }):
            with patch("app.services.ai_service.httpx.post", return_value=success) as post:
                result = respond_to_emergency_chat(
                    "There is smoke in the kitchen",
                    "en",
                    [{"role": "user", "content": "I smell smoke"}],
                    "fire",
                    ["Leave through a safe exit."],
                )
        self.assertEqual(result["status"], "connected")
        self.assertTrue(result["in_scope"])
        payload = post.call_args.kwargs["json"]
        self.assertIn("emergency-only assistant", payload["messages"][0]["content"])
        self.assertIn("3-5 numbered action lines", payload["messages"][0]["content"])
        self.assertIn("Do not make 'Call 112' the whole answer", payload["messages"][0]["content"])
        self.assertEqual(payload["messages"][-2]["content"], "I smell smoke")

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
