"""Gemini API helper used by the ResQLink backend."""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai


# Load the backend/.env file without printing or exposing its contents.
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)


def _format_api_error(error) -> str | None:
    """Format a Gemini ErrorEvent without exposing credentials."""
    if error is None:
        return None

    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
    else:
        code = getattr(error, "code", None)
        message = getattr(error, "message", None)

    if code or message:
        return f"{code or 'API error'}: {message or 'No message returned.'}"

    return str(error)


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
        print(
            f"Gemini accepted the request. Interaction ID: {interaction_id}",
            flush=True,
        )

        deadline = time.monotonic() + 120

        while True:
            interaction = client.interactions.get(id=interaction_id)
            status = str(interaction.status).lower().split(".")[-1]

            if status == "completed":
                break

            if status in {"failed", "cancelled", "canceled", "incomplete", "budget_exceeded"}:
                details = _format_api_error(getattr(interaction, "error", None))

                # Background polling can expose only the terminal status.
                # The streaming endpoint delivers structured ErrorEvents.
                if status == "failed" and not details:
                    print("Retrieving Gemini's detailed error event...", flush=True)
                    try:
                        for event in client.interactions.get(
                            id=interaction_id,
                            stream=True,
                        ):
                            if getattr(event, "event_type", None) == "error":
                                details = _format_api_error(
                                    getattr(event, "error", None)
                                )
                                if details:
                                    break
                    except Exception as stream_error:
                        details = (
                            "Could not retrieve the error event: "
                            f"{type(stream_error).__name__}: {stream_error}"
                        )

                if not details:
                    details = "Gemini returned a terminal status without error details."

                raise RuntimeError(
                    f"Gemini interaction {status}. "
                    f"Interaction ID: {interaction_id}. Details: {details}"
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
            f"Gemini interaction completed without text. Interaction ID: {interaction_id}"
        )

    print("Gemini response received.", flush=True)
    return reply.strip()


if __name__ == "__main__":
    reply = generate_reply("Reply with exactly: Gemini connected.")
    print(reply)
