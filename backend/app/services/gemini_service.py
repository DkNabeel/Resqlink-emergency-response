"""Gemini API helper used by the ResQLink backend."""

import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai


# Load the backend/.env file without exposing its contents.
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)


def generate_reply(message: str) -> str:
    """Send one text prompt to Gemini and return its text response."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string.")

    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL")

    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing from backend/.env.")
    if not model:
        raise ValueError("GEMINI_MODEL is missing from backend/.env.")

    print(f"Preparing Gemini client. Model: {model}", flush=True)

    # ResQLink currently needs a single response, so use the standard
    # generateContent API rather than the newer Interactions API.
    with genai.Client(
        api_key=api_key,
        http_options={
            "timeout": 60000,
            "retry_options": {"attempts": 0},
        },
    ) as client:
        print("Sending request to Gemini. Please wait...", flush=True)

        response = client.models.generate_content(
            model=model,
            contents=message.strip(),
        )

    reply = response.text
    if not reply:
        raise RuntimeError(
            "Gemini returned no text. Check the model response and safety finish reason."
        )

    print("Gemini response received.", flush=True)
    return reply.strip()


if __name__ == "__main__":
    reply = generate_reply("Reply with exactly: Gemini connected.")
    print(reply)
