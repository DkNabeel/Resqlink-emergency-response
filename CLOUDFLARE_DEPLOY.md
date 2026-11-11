# ResQLink — Cloudflare Free deployment

This branch runs a **Python Worker with FastAPI** on Cloudflare's Free plan. It keeps the existing multilingual emergency classifier and curated safety guidance, uses **Groq** for optional AI classification, calls Open-Meteo for on-demand weather, and exposes the offline package endpoint used by the Expo app.

No Cloudflare Containers or Workers Paid plan are used. The Cloudflare Worker is stateless in this first demo: server-side SQLite persistence, SACHET background collection, saved location history and verified facility storage are deliberately disabled. The mobile app still caches its downloaded offline package locally in Expo SQLite.

## Cloudflare Free limits to be aware of

- 100,000 Worker requests per day.
- 10 ms CPU time per HTTP request (network waiting time does not count).
- D1 is available on Free (not configured in this first demo branch).
- Do not treat this student prototype as a real emergency dispatch service.

Official limits: https://developers.cloudflare.com/workers/platform/limits/

## 1. Requirements

- Node.js
- `uv` (Python package/project manager)
- A Cloudflare account (Free plan is enough)
- A Groq API key (optional but required for Groq AI classification)

Install uv on Windows (one option):

```powershell
winget install --id=astral-sh.uv -e
```

## 2. Get the Cloudflare branch

From PowerShell:

```powershell
git fetch origin
git switch cloudflare-demo
```

## 3. Install the Python Worker tooling

Run from the repository root:

```powershell
uv sync
```

## 4. Configure API settings in one local file

All local Worker settings are kept together in the repository-root `.dev.vars` file. You do not need one file per API.

Create your local file from the safe template:

```powershell
Copy-Item .dev.vars.example .dev.vars
notepad .dev.vars
```

Add your Groq key to the `GROQ_API_KEY=` line and save. Do not add quotes unless they are part of the key. The root `.dev.vars` file is gitignored and must never be committed or shared.

**API key requirements in this Cloudflare demo:**

- **Groq:** requires `GROQ_API_KEY`. This is the only API credential currently required by the Worker for AI classification.
- **Open-Meteo weather:** no API key required.
- **OpenStreetMap Overpass facility discovery:** no API key required.
- **NDMA SACHET:** no API key, but background syncing is disabled in this stateless demo.
- **OpenRouteService** and `FACILITY_ADMIN_TOKEN`: belong to optional features in the original full backend and are not used by this Cloudflare Worker yet. Do not create or add those keys now.

For local testing, Wrangler reads `.dev.vars`. For the deployed Worker, add the Groq key separately as a Cloudflare secret (local files are not uploaded):

```powershell
uv run pywrangler secret put GROQ_API_KEY
```

Paste the same Groq key when prompted. Never put it in the mobile app or commit it.

## 5. Test locally first

```powershell
uv run pywrangler dev
```

Open the local URL printed by Wrangler (normally http://localhost:8787):

- `/health`
- `/system/status`
- `/docs`

The local worker uses Cloudflare's local runtime simulator. Confirm that `/health` returns status `ok` and that `/system/status` reports AI provider `Groq`.

## 6. Deploy to Cloudflare Free

Stop the local dev process and run:

```powershell
uv run pywrangler deploy
```

Accept the prompt to create/enable the free `workers.dev` subdomain if asked. Wrangler prints the public Worker URL, for example:

`https://resqlink-emergency-api.<your-subdomain>.workers.dev`

## 7. Connect Expo Go to the deployed API

Create `mobile/.env` (copy `mobile/.env.example`) and set the exact URL Wrangler printed:

```env
EXPO_PUBLIC_API_BASE_URL=https://resqlink-emergency-api.<your-subdomain>.workers.dev
```

Then:

```powershell
cd mobile
npm install
npx expo start --tunnel
```

Scan the QR code using Expo Go. The Expo tunnel only loads the development app onto the phone; API calls go directly to the public Cloudflare URL.

Restart Expo after changing `.env`.

## What works in this free demo

- FastAPI routes running on Cloudflare Python Workers.
- Groq classification when `GROQ_API_KEY` is configured.
- Multilingual English/Hindi/Kannada rule-based fallback.
- Curated emergency instructions and India emergency number 112.
- On-demand Open-Meteo weather when the emergency request includes GPS and `include_weather=true`.
- Download and local SQLite caching of offline safety guides in Expo Go.
- Unverified OpenStreetMap nearby-facility discovery endpoint.

## Not enabled in this first free demo

- Persistent server-side SQLite data, saved user locations or verified facilities.
- SACHET alert ingestion, storage or background refresh.
- Offline map tiles and push notifications.
- Live traffic conditions (the current road route provider is an ETA from road-network data, not live traffic).

The server returns explicit empty alert/facility storage fields rather than pretending they are populated. The phone's saved offline package remains available offline, but contains only the curated guidance and 112 in this build.

This is a student prototype for presentation and testing only. Never rely on it as an emergency dispatch service; call 112 and follow official authorities.
