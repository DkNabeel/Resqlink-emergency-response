import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)


def generate_reply(message: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL")

    if not api_key or not model:
        raise ValueError("Set GEMINI_API_KEY and GEMINI_MODEL in backend/.env")

        print(f"Preparing Gemini client. Model: {model}", flush=True)

    with genai.Client(
        api_key=api_key,
        http_options={
            "timeout": 30000,
            "retry_options": {"attempts": 0},
        },
    ) as client:
        print("Sending request. Waiting for Gemini...", flush=True)

        response = client.interactions.create(
            model=model,
            input=message,
        )

        print("Response received.", flush=True)

    return response.output_text


if __name__ == "__main__":
    reply = generate_reply("Reply with exactly: Gemini connected.")
    print(reply)