# ResQLink Mobile (Expo React Native)

This is the Android/iOS client foundation. It includes:
- Foreground GPS permission and current location retrieval.
- Emergency submission to the FastAPI backend.
- English, Hindi and Kannada selection.
- Download and conditional refresh of the location-scoped offline package.
- Persistent local SQLite cache using expo-sqlite.
- Basic offline keyword guidance from the last saved package plus 112.

## Requirements

- Node.js 22.13 or newer for Expo SDK 58.
- Android phone with Expo Go compatible with SDK 58, or an Android development build.

## Connect to the Cloudflare backend

1. Deploy the backend by following [CLOUDFLARE_DEPLOY.md](../CLOUDFLARE_DEPLOY.md).
2. Copy the public `workers.dev` URL printed by Wrangler.
3. Create `.env` in this `mobile` folder (copy `.env.example`) and set:

```env
EXPO_PUBLIC_API_BASE_URL=https://YOUR-WORKER.workers.dev
```

Do not add a trailing slash. Do not put Groq or other backend secrets in this file.

## Run the app in Expo Go

From this `mobile` folder:

```powershell
npm install
npx expo start --tunnel
```

Scan the QR code using Expo Go. The Expo tunnel lets the phone load the development app; the app's API requests go directly to the public Cloudflare backend. Restart Expo after editing `.env` so the new URL is bundled into the app.

## Local backend development (optional)

For local development only, set `EXPO_PUBLIC_API_BASE_URL` to your laptop's LAN IPv4 address, for example `http://192.168.1.20:8000`. The phone and laptop must be on the same Wi-Fi. Do not use `127.0.0.1` on the phone.

Start FastAPI from the `backend` folder:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Offline limits

The phone's SQLite cache stores the most recently fetched package for each rounded coordinate/language key and reuses the ETag on refresh. If the backend is unreachable, the app can show the saved package and basic keyword-matched guidance from that package. This is not full offline NLP, not a downloaded map, and not a replacement for calling 112. No new government alerts, weather or traffic can arrive while disconnected.
