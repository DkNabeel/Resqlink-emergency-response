# ResQLink Mobile (Expo React Native)

ResQLink has two operating modes: online emergency assistance and a limited offline survival mode.

## Included in this branch

- Emergency-only conversational endpoint powered by Groq, with up to ten recent chat messages.
- English, Hindi and Kannada interface and offline guidance.
- Location and notification permission gate before entering the app.
- Online map showing the current GPS position and nearby emergency facilities.
- Facility list labels verified project records separately from unverified OpenStreetMap candidates.
- Tap a facility to open driving directions in Google Maps. Directions are not checked against live disaster hazards.
- Separate weather pop-up for temperature, humidity, wind and rain probability using Open-Meteo.
- Downloaded offline package containing emergency instructions, India emergency number 112, SACHET alert snapshot, verified facilities and nearby unverified OpenStreetMap candidates when discovery succeeds.
- Expo SQLite keeps only the latest downloaded area package to limit storage.
- Best-effort background location task can refresh the latest area package and raise local notifications for newly matched SACHET alerts.

## Requirements

- Node.js 22.13 or newer for Expo SDK 58.
- Android phone and Android development build for background location.
- Laptop and phone on the same Wi-Fi for the local FastAPI backend.
- Grant foreground location and notification permissions. Background location is also requested; the operating system controls whether and how often the task runs.

## Configure the backend address

Copy .env.example to .env and set EXPO_PUBLIC_API_BASE_URL to your laptop's LAN IPv4 address. Do not use 127.0.0.1 from the phone; that points to the phone itself.

Example (replace the address with the laptop's actual IPv4):

```env
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.20:8000
```

Start FastAPI so other devices on the LAN can reach it:

```powershell
cd D:\PROJECTS\Resqlink-emergency-response\backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Allow TCP port 8000 through Windows Defender Firewall on the private network if prompted. Do not expose the development server to public networks.

## Install and run the online UI

```powershell
cd D:\PROJECTS\Resqlink-emergency-response\mobile
npm install
npx expo start
```

The online map and foreground UI can be checked in a compatible Expo Go version. Background location tasks and persistent background protection require a native development build; they cannot be fully tested in Expo Go on Android. For a local Android development build, use Android Studio/SDK and:

```powershell
npx expo prebuild
npx expo run:android
```

A new native build is required after changing location, notification or map native configuration.

## Offline limits and safety notes

- Offline mode uses multilingual built-in keyword guidance and the latest successfully saved area package. It does not use Groq.
- Cached facility candidates from OpenStreetMap are community-mapped and labelled unverified. Confirm details before relying on them.
- The current map view uses online map tiles. Offline map tiles and offline road-by-road routing are not implemented in this branch.
- Facility route buttons open an external map app when connectivity is available. A normal route estimate is not a verified safe evacuation route.
- Background refresh requests a ten-minute update interval, but Android/iOS can delay, throttle or stop background work. It is best-effort, not a guaranteed timer.
- The current alert task can issue local notifications after it wakes and fetches a package with location-matched SACHET alerts. It is not a remote push-notification service; server-driven push registration and delivery are not implemented.
- The SACHET polygon endpoint has returned HTTP 403 in the current environment. Alerts without confirmed geographic matching must remain visibly unverified.
- Weather is contextual information, not an official disaster warning.
- No absence of alerts or facilities proves an area is safe. Call 112 in India and follow official responder instructions.

## Native Android map configuration

Expo Go includes the React Native Maps module for foreground testing. A standalone Android development or release build needs a Google Maps Android API key configured in the native Expo config before building. Do not commit the key to a public repository; use an appropriate local environment or build secret. Background location also requires a native development build and OS permission approval.
