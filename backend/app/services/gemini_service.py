"""Gemini API helper used by the ResQLink backend."""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai


# Load the backend/.env file without printing or exposing its contents.
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)


def generate_reply(message: str) -> str:
    """Send a text prompt to Gemini and wait for its background interaction."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string.")

    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL")

    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing from backend/.env.")
    if not model:
        raise ValueError("GEMINI_MODEL is missing from backend/.env.")

    print(f"Preparing Gemini client. Model: {model}", flush=True)

    # Background execution avoids keeping one HTTP request open while the
    # model is generating. We poll the interaction until it completes.
    with genai.Client(
        api_key=api_key,
        http_options={
            "timeout": 30000,
            "retry_options": {"attempts": 0},
        },
    ) as client:
        print("Submitting background request to Gemini...", flush=True)

        interaction = client.interactions.create(
            model=model,
            input=message.strip(),
            background=True,
        )

        interaction_id = interaction.id
        print("Gemini accepted the request. Waiting for completion...", flush=True)

        deadline = time.monotonic() + 120

        while True:
            interaction = client.interactions.get(interaction_id)
            status = str(interaction.status).lower().split(".")[-1]

            if status == "completed":
                break

            if status in {"failed", "cancelled", "canceled"}:
                error = getattr(interaction, "error", None)
                raise RuntimeError(
                    f"Gemini interaction {status}. Details: {error or 'No error details returned.'}"
                )

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Gemini is still processing after 120 seconds. "
                    f"Interaction ID: {interaction_id}"
                )

            print(f"Gemini status: {status}. Checking again in 2 seconds...", flush=True)
            time.sleep(2)

    reply = interaction.output_text
    if not reply:
        raise RuntimeError(
            "Gemini completed the interaction but returned no text."
        )

    print("Gemini response received.", flush=True)
    return reply.strip()


if __name__ == "__main__":
    reply = generate_reply("Reply with exactly: Gemini connected.")
    print(reply)
