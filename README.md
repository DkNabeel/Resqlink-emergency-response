# ResQLink — AI-Based Multilingual Emergency Response

ResQLink is a planned mobile emergency-assistance application. It combines AI/NLP, multilingual processing, GPS, geospatial analysis, official public alerts, nearby emergency facilities and offline information.

**Important:** A feature is not considered implemented merely because its backend file exists. See the status notes below and test the local application.

## Current backend stack

- Python
- FastAPI and REST endpoints
- SQLite
- Google Gemini API (language-processing integration is being verified)
- NDMA SACHET CAP/RSS feed for official India disaster alerts
- HTTPX for feed retrieval
- ETag / Last-Modified conditional feed requests
- Haversine distance and CAP polygon/circle matching

## Backend setup

Open a terminal in the backend folder.

~~~powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
~~~

Copy .env.example to .env, then configure your own API key and model. Never commit .env.

~~~powershell
python -m app.database.init_db
uvicorn app.main:app --reload
~~~

Open the API documentation at http://127.0.0.1:8000/docs.

## Implemented backend endpoints in this code snapshot

| Endpoint | Purpose |
|---|---|
| GET /health | Backend/database health |
| POST /emergency | Receives an emergency message; Gemini is not yet wired into this endpoint |
| GET /alerts | Reads stored official alert records |
| GET /alerts/nearby | Matches alert CAP geometry or labels locality-only results as unverified |
| GET /alerts/sync-status | Shows SACHET collector status |
| POST /locations/resolve | Saves a supplied GPS/manual location, or tries configured IP/last-known fallback |
| GET /locations/{device_id}/last-known | Reads the latest location saved for a device |
| GET /facilities | Lists stored facilities |
| GET /facilities/nearby | Finds stored facilities within a radius |

## Official alert collection

The default feed is the NDMA SACHET India CAP RSS feed:

https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml

The backend collector starts with FastAPI when SACHET_SYNC_ENABLED=true and checks the feed every SACHET_REFRESH_SECONDS (minimum 60 seconds). It uses ETag and Last-Modified request headers when supplied by the feed server. An HTTP 304 means the feed has not changed, so the existing database cache is retained.

The parser stores the source title, description, CAP fields and any polygon/circle geometry present in the feed. If the feed does not provide machine-readable affected-area geometry, ResQLink labels the match as unverified. It must not invent an alert radius or tell a user they are safe.

## Location fallback

POST /locations/resolve accepts a device ID and, when available, latitude/longitude. If coordinates are omitted, the backend can attempt IP geolocation (only when explicitly enabled) and then use the last saved device location.

IP geolocation is approximate and may point to a mobile carrier gateway or population centre. It must not be used to decide that a person is inside or outside a precise hazard zone. IP lookup is disabled by default. When enabled, the connecting public IP is sent to the configured provider; review that provider's privacy policy, terms and limits before using it beyond development.

Offline maps and cached data on the phone must be implemented in the mobile app. The backend cannot fetch fresh feeds or push data to a phone that has no network connection.

## Safety and notification boundaries

Government Cell Broadcast/SMS remains separate from ResQLink. ResQLink should display the original government source and timestamps.

Firebase Cloud Messaging must not be treated as a life-critical emergency-alert delivery channel. It may be considered for ordinary app updates, while official government warning channels and the in-app alert view remain separate. Notification delivery is never guaranteed.

## Automated checks

Run the unit tests from the backend folder:

~~~powershell
python -m unittest discover -s tests -v
~~~

These tests validate local parsing and geospatial helper logic. They do not test live NDMA availability, Gemini API access, mobile GPS permissions, offline maps or notification delivery.

## Environment variables

See .env.example. Important settings:

- GEMINI_API_KEY, GEMINI_MODEL
- SACHET_FEED_URL
- SACHET_SYNC_ENABLED
- SACHET_REFRESH_SECONDS
- IP_GEOLOCATION_ENABLED
- IP_GEOLOCATION_URL_TEMPLATE

## Project roadmap

1. Project structure and environment — basic setup exists.
2. FastAPI and REST API — basic endpoints exist.
3. SQLite and facility CRUD — user-confirmed completed.
4. Gemini integration — still being diagnosed; not yet connected to /emergency.
5. Emergency NLP/context extraction.
6. Mobile GPS and permission flow.
7. Geospatial analysis and affected-area handling.
8. Weather, traffic and additional official information providers.
9. Mobile offline map/data cache.
10. Multilingual response processing.
11. Mobile application and supplementary notification integration.
12. End-to-end testing, documentation and viva preparation.

The current backend batch adds official alert collection, alert persistence, location fallback endpoints and nearby-facility distance lookup. Mobile-specific features remain future work.
