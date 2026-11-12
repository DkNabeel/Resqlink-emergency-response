# ResQLink — AI-Based Multilingual Emergency Response

ResQLink is a mobile emergency-response project. This repository currently contains the FastAPI backend, SQLite persistence, multilingual rule-based emergency intent handling, NDMA SACHET alert ingestion, geospatial matching, facility management and an on-demand weather forecast adapter.

**Implementation:** The emergency endpoint uses optional Groq AI intent classification when configured, with deterministic multilingual keyword detection as a fallback. Safety instructions remain curated local guidance. The Expo React Native client is in mobile/. It includes foreground GPS, emergency submission, nearby facility discovery and a SQLite-backed cache. Facility distances are approximate straight-line distances; facility buttons open Google Maps for external driving directions. Custom in-app online/offline routing, offline map tiles and push notification delivery are not implemented.

## Backend setup

Run these commands in the backend folder:

~~~powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
~~~

Copy .env.example to .env and configure private values. Never commit .env.

~~~powershell
python -m app.database.init_db
python -m uvicorn app.main:app --reload
~~~

API documentation: http://127.0.0.1:8000/docs

## Free cloud deployment (Render)

The repository includes a `render.yaml` Blueprint for deploying the existing FastAPI backend as a free Render web service.

1. Sign in to Render and choose **New → Blueprint**.
2. Connect this GitHub repository and select the `main` branch.
3. Review the `resqlink-api` service and select the **Free** plan.
4. Before or after the first deploy, open the service's **Environment** settings and add:
   - `GROQ_API_KEY` (required for Groq classification)
   - `FACILITY_ADMIN_TOKEN` (optional facility-verification protection)
5. Deploy and wait for the service to become **Live**.
6. Test `https://YOUR-SERVICE.onrender.com/health` and `/system/status`.

Use the public Render URL as `EXPO_PUBLIC_API_BASE_URL` in `mobile/.env`, for example:
`EXPO_PUBLIC_API_BASE_URL=https://YOUR-SERVICE.onrender.com`.
Restart Expo after changing the mobile environment file.

**Free-plan limitations:** Render free web services sleep after 15 minutes without incoming traffic and may take about a minute to wake on the next request. Their filesystem is ephemeral: the local SQLite database is reset after restarts, redeploys or sleep. The SACHET collector will repopulate alert data after startup, but manually entered facilities and other local database changes are not durable. This deployment is intended for demos/testing, not production emergency use. Do not rely on this prototype as an emergency dispatch service.


## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /health | API/database health and record counts |
| GET | /system/status | Provider and implementation status |
| POST | /emergency | Multilingual emergency intent, safety guidance, India emergency contact, nearby context and optional weather forecast |
| GET | /alerts | Stored SACHET alert records |
| GET | /alerts/nearby | Match available CAP geometry or return explicitly unverified matches |
| GET | /alerts/sync-status | SACHET collector status |
| POST | /locations/resolve | Save GPS/manual location or use configured fallback |
| GET | /locations/{device_id}/last-known | Retrieve saved location and freshness |
| GET | /facilities | List/filter stored facilities |
| POST | /facilities | Add a facility (unverified by default) |
| PUT | /facilities/{facility_id} | Update a facility; resets its verification |
| DELETE | /facilities/{facility_id} | Delete a facility |
| POST | /facilities/{facility_id}/verification | Verify/unverify a facility with admin token |
| GET | /facilities/nearby | Search facilities by straight-line distance |
| GET | /weather/nearby | Current model conditions and hourly forecast from Open-Meteo |\n| GET | /facilities/discover | Find nearby OpenStreetMap facility candidates (unverified) |
| GET | /offline/package | Download language-specific guides, 112, nearby verified facilities and location-matched alert snapshot; supports ETag/304 conditional refresh |

## Emergency request example

POST /emergency:

~~~json
{
  "message": "There is smoke and fire in my building",
  "language": "en",
  "latitude": 12.9716,
  "longitude": 77.5946,
  "radius_km": 10
}
~~~

When both coordinates are supplied, the endpoint also requests a short Open-Meteo weather forecast by default. Set "include_weather": false to skip this provider call, or set "weather_forecast_hours" from 1 to 24. If the weather provider fails, the emergency analysis still returns and weather_context is marked unavailable.

Supported response languages: en, hi, kn. The endpoint uses the Groq chat completions API when GROQ_API_KEY is configured. The default primary model is qwen/qwen3.8-27b, with openai/gpt-oss-20b as a backup model. The integration requests JSON output and uses bounded request timeouts. Groq classifies the report but does not generate safety instructions. Set use_ai=false per request to skip AI classification. If the provider is unavailable or its free-tier limits are reached, local multilingual NLP and curated safety guidance continue to work. The caller explicitly selects the response language. The local rule-based detector currently recognizes fire, flood, earthquake, cyclone, landslide, tsunami, lightning, gas leak, medical emergency, road accident and violence keywords. Multiple detected types are returned; guidance and suggested facility types are combined for all detected hazards, with one primary category selected by a fixed priority order. This is a demo fallback, not a trained classifier or medical triage system. Weather fetching from `/emergency` is opt-in (`include_weather=true`) so the basic emergency response does not wait on an external weather provider.

The emergency response includes India's unified ERSS number 112. The Ministry of Home Affairs describes 112 as the nationwide single emergency number for police, fire, health and other emergencies: https://www.mha.gov.in/emergency-response-support-system-erss

## Weather endpoint

GET /weather/nearby?latitude=12.9716&longitude=77.5946&forecast_hours=12

The endpoint requests current model conditions and up to 24 forecast hours, normalizes precipitation probability, precipitation amount, weather code, wind and humidity, and caches responses in memory for 10 minutes by default. On provider failure, a cached snapshot up to 24 hours old may be returned with cache_status=stale and an explicit warning.

Weather provider: https://open-meteo.com/en/docs

Attribution is included in every response. The free Open-Meteo API is intended for non-commercial use and attribution is required; check current terms before deployment or commercial use: https://open-meteo.com/en/terms

Weather model output is not an official government alert, a local sensor reading or a guarantee of conditions. Do not use it alone to decide whether an area is safe or whether to evacuate.

## Facilities and verification

New facilities are marked unverified. Store the organization/source name in source_name. A verification action requires FACILITY_ADMIN_TOKEN in backend/.env and the X-Admin-Token header. Verification notes should say exactly what source was checked. Any later edit resets the record to unverified so changed coordinates or phone numbers are not silently treated as checked.

Example facility payload:

~~~json
{
  "name": "Example District Hospital",
  "facility_type": "hospital",
  "latitude": 12.9716,
  "longitude": 77.5946,
  "address": "Enter a checked address",
  "phone": "Enter a checked phone number",
  "source_name": "Official district directory"
}
~~~

Do not use this example as a real facility. Only enter verified real-world records after checking them against a current official source. Nearby distance is straight-line distance, not road distance or travel time.

## Official alert collection

Default source: https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml

The backend retrieves RSS and linked CAP detail documents and stores sender, event, urgency, severity, certainty, timestamps, language blocks, area text and geocodes. The linked polygon endpoint has returned HTTP 403 in the current development environment. The backend therefore does not claim polygon-verified matching for those alerts. District/locality text matches are weaker and labelled as such.

## Location and offline limitations

- GPS coordinates are provided by a future mobile client; this backend does not request a phone's GPS permission.
- IP geolocation is approximate and disabled by default.
- A saved GPS position may become stale and must be checked using its recorded timestamp.
- `/offline/package` returns a location-scoped data snapshot and supports `ETag` / `If-None-Match` so a mobile client can skip downloading an unchanged package. The mobile app must store and use the last successful response locally; the backend cannot retrieve live government feeds when the phone has no network. A `304 Not Modified` response means the client should retain its previously saved package.
- The mobile facility finder shows approximate straight-line distances. Google Maps calculates external driving directions when the user taps a facility button.\n- GET /facilities/discover searches OpenStreetMap community-mapped candidates. Results are never stored or verified automatically; confirm them from current official records before relying on them.
- Push notification delivery is not guaranteed and must not replace official warning channels.

## Tests

Run from the backend folder:

~~~powershell
python -m unittest discover -s tests -v
~~~

The test suite includes parser/geospatial tests, multilingual emergency tests, weather normalization/cache tests and API integration tests with an isolated temporary SQLite database. CI does not call live SACHET or Open-Meteo services.

## Environment variables

See .env.example. Important settings:

- GROQ_API_KEY, GROQ_MODEL, GROQ_FALLBACK_MODEL, AI_ENABLED, GROQ_REQUEST_TIMEOUT_SECONDS and AI_TOTAL_TIMEOUT_SECONDS
- SACHET_FEED_URL, SACHET_SYNC_ENABLED, SACHET_REFRESH_SECONDS
- IP_GEOLOCATION_ENABLED and IP_GEOLOCATION_URL_TEMPLATE
- FACILITY_ADMIN_TOKEN (protects facility verification endpoint)
- WEATHER_CACHE_TTL_SECONDS
- LOG_LEVEL


## Driving directions

The current submission build does not calculate road routes inside ResQLink. Facility rows show approximate Haversine straight-line distance, while the Google Maps button opens external turn-by-turn driving directions. Custom online and offline route algorithms are deferred for the next development phase; Docker is not required for the current demo.

## Nearby facility discovery

GET /facilities/discover?latitude=12.97&longitude=77.59&radius_km=5 queries the OpenStreetMap Overpass public service. Results are not official directory records. They are unverified suggestions only, cached for 15 minutes and not inserted into the ResQLink database. Verify every real facility against an official source before setting its verification_status to verified.


## Mobile application

See mobile/README.md. The Expo React Native source includes foreground GPS, a language selector, emergency message submission, a location-based offline-package downloader, ETag conditional refresh and SQLite persistence on the phone. Set EXPO_PUBLIC_API_BASE_URL to the backend's laptop LAN address; the phone and laptop must be on the same Wi-Fi for local development. The client does not include offline visual map tiles, custom offline road routing or push notification delivery. Google Maps directions require internet connectivity.
