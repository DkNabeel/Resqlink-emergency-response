# ResQLink — AI-Based Multilingual Emergency Response

ResQLink is a planned mobile emergency-assistance application. The current submission demo backend receives emergency messages, detects common emergency intents, returns general safety guidance in English/Hindi/Kannada, and can attach nearby stored facilities and official SACHET alerts when GPS coordinates are supplied.

Important: The emergency intent module is a transparent local keyword-based NLP fallback. Gemini is not yet connected to this endpoint. Native mobile screens, GPS permission flow, offline maps/cache and push notifications remain to be implemented.

## Backend setup

From the backend folder:

~~~powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
~~~

Copy .env.example to .env and set private values. Never commit .env.

~~~powershell
python -m app.database.init_db
python -m uvicorn app.main:app --reload
~~~

API documentation: http://127.0.0.1:8000/docs

## Main endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /health | Backend and database health |
| POST | /emergency | Detect emergency intent, return multilingual guidance, optionally attach nearby facilities and alerts |
| GET | /alerts | Read stored SACHET records |
| GET | /alerts/nearby | Match available alert geometry or explicitly labelled locality-text results |
| GET | /alerts/sync-status | View SACHET collector state |
| POST | /locations/resolve | Save GPS/manual location or attempt configured fallback |
| GET | /locations/{device_id}/last-known | Retrieve saved location |
| GET | /facilities | List stored emergency facilities |
| GET | /facilities/nearby | Find stored facilities within a radius |

## Emergency API example

Send this JSON to POST /emergency:

~~~json
{
  "message": "There is a fire and smoke in my building",
  "language": "en",
  "latitude": 12.9716,
  "longitude": 77.5946,
  "radius_km": 10
}
~~~

Coordinates above are examples only. Omit both coordinates if unavailable. The API still returns intent and guidance, but cannot calculate nearby facilities or geographically compare alerts without a location.

Supported response languages are en, hi and kn. Unsupported language values fall back to English.

## Official alert collection

Default source: https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml

The backend checks the RSS feed every five minutes by default and retrieves linked CAP details. CAP status, sender, event, severity, urgency, certainty, effective/expiry timestamps, language blocks and district geocodes are stored. The separate SACHET polygon endpoint currently returns HTTP 403 in this environment, so polygon-verified affected-area matching is not available. Locality text matching is a weaker fallback and is labelled accordingly.

## Important safety and implementation limits

- IP geolocation is approximate and disabled by default.
- Stale GPS positions must not be treated as current.
- Text or district matching does not establish polygon-level hazard boundaries.
- The application must never claim a location is guaranteed safe.
- Empty nearby-facility results may mean the facilities table has not been populated with verified records.
- Emergency guidance is general; users must follow official local responders.
- The current emergency endpoint uses local keyword NLP, not Gemini.
- Mobile GPS permissions, on-device offline maps/cache, weather/traffic integrations and push notifications are not implemented in this backend snapshot.

## Tests

Run from the backend folder:

~~~powershell
python -m unittest discover -s tests -v
~~~

Tests cover local emergency intent detection, multilingual guidance, SACHET CAP parsing and basic geospatial logic. They do not prove live Gemini access, live polygon access or mobile application behavior.

## Submission status

Working in this backend:
- FastAPI REST API and SQLite persistence
- SACHET RSS and CAP detail ingestion
- Multilingual emergency intent and guidance endpoint
- Nearby stored-facility distance lookup
- Available alert matching with unverified handling

Still required:
- Gemini integration into emergency analysis
- Native mobile application and permission flow
- Mobile offline map and emergency-data cache
- Weather/traffic and additional official providers
- Supplementary app notifications
- Full mobile end-to-end testing and research-paper validation
