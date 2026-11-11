# ResQLink Mobile (Expo React Native)

This is the Android/iOS client foundation. It includes:
- Foreground GPS permission and current location retrieval.
- Emergency submission to the FastAPI backend.
- English, Hindi and Kannada selection.
- Download and conditional refresh of the location-scoped offline package.
- Persistent local SQLite cache using expo-sqlite.
- Basic offline keyword guidance from the last saved package plus 112.

## Connect to Cloudflare Free

1. Deploy the backend by following [CLOUDFLARE_DEPLOY.md](../CLOUDFLARE_DEPLOY.md).
2. Copy the public `workers.dev` URL printed by Wrangler.
3. Create `.env` in this `mobile` folder and set:

```env
EXPO_PUBLIC_API_BASE_URL=https://YOUR-WORKER.workers.dev
```

Do not add a trailing slash. Do not put Groq or other backend secrets in this file.

## Run in Expo Go

From this `mobile` folder:

```powershell
npm install
npx expo start --tunnel
```

Scan the QR code in Expo Go. The Expo tunnel loads the development app; API requests go directly to the public Cloudflare backend. Restart Expo after editing `.env`.

## Local FastAPI development (optional)

For the original full local backend, follow the root README and set `EXPO_PUBLIC_API_BASE_URL` to your laptop's LAN IPv4 address, for example `http://192.168.1.20:8000`. The phone and laptop must be on the same Wi-Fi.

## Offline limits

The phone's SQLite cache stores the most recently fetched package for each rounded coordinate/language key and reuses the ETag on refresh. The Cloudflare Free demo package contains curated guides and 112, not server-side live alerts or a verified facility directory. This is not full offline NLP, not a downloaded map, and not a replacement for calling 112.
