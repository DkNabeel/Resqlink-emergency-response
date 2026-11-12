# ResQLink Mobile (Expo React Native)

ResQLink has two operating modes: online emergency assistance and a limited offline survival mode.

## Included in this branch

- Emergency-only conversational endpoint powered by Groq, with up to ten recent chat messages.
- English, Hindi and Kannada interface and offline guidance.
- Location and notification permission gate before entering the app.
- Online map showing the current GPS position and nearby emergency facilities.
- Facility list labels verified project records separately from unverified OpenStreetMap candidates.
- Facility results show approximate straight-line distance from the selected location. Tap **Google Maps** to open externally calculated driving directions; they are not checked against live disaster hazards.
- Separate weather pop-up for temperature, humidity, wind and rain probability using Open-Meteo.
- SQLite keeps the latest cached emergency guidance and facility snapshot for fallback display.
- Best-effort background location task can refresh the latest area package and raise local notifications for newly matched SACHET alerts.

## Requirements

- Node.js 22.13 or newer for Expo SDK 58.
- Android phone and Android development build for background location.
- Laptop connected to the phone's personal hotspot (or both devices on the same local Wi-Fi network) for the local FastAPI backend.
- Grant foreground location and notification permissions. Background location is also requested; the operating system controls whether and how often the task runs.

## Configure the backend address (phone hotspot or Wi-Fi)

A separate Wi-Fi router and Cloudflare tunnel are **not required** for local testing. You can turn on your phone's personal hotspot, connect the laptop to it, and let the ResQLink app on that same phone call the laptop's local FastAPI server.

1. Turn on Personal Hotspot on the phone and connect your laptop to that hotspot.
2. On the laptop, open Command Prompt and run `ipconfig`. Under **Wireless LAN adapter Wi-Fi**, copy the laptop's **IPv4 Address**. This is the laptop's address on the hotspot network.
3. Copy `.env.example` to `.env` in this `mobile` folder and set the address using the laptop's real IPv4 value:

```env
EXPO_PUBLIC_API_BASE_URL=http://192.168.x.x:8000
```

Replace `192.168.x.x` with the exact laptop IPv4 address. Do not use `localhost`, `127.0.0.1` or `0.0.0.0` in the mobile app: those are not the laptop's reachable address from the phone.

4. Start FastAPI on the laptop so it listens on the hotspot network interface:

```powershell
cd backend
py -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

5. On the phone, open its browser and visit `http://<laptop-ip>:8000/health`, replacing `<laptop-ip>` with the same IPv4 address. A JSON response containing `"status":"ok"` confirms the phone can reach the backend.
6. If that page does not open, check Windows Defender Firewall and allow inbound TCP port 8000 for the active hotspot network. Also confirm FastAPI is still running in the terminal.
7. After changing `.env`, restart Expo from this `mobile` folder so it picks up the new public environment variable:

```powershell
npx expo start -c
```

The phone hotspot must allow communication between the phone and its connected laptop. If the phone browser cannot open the laptop's `/health` URL even with FastAPI listening and the firewall allowed, that hotspot/device configuration is blocking local peer access; verify that before changing app code or adding a tunnel.

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
- The current map view uses online map tiles. Custom in-app online/offline road routing is deferred; the current demo opens Google Maps for driving directions and does not require Docker.
- Facility route buttons open an external map app when connectivity is available. A normal route estimate is not a verified safe evacuation route.
- Background refresh requests a ten-minute update interval, but Android/iOS can delay, throttle or stop background work. It is best-effort, not a guaranteed timer.
- The current alert task can issue local notifications after it wakes and fetches a package with location-matched SACHET alerts. It is not a remote push-notification service; server-driven push registration and delivery are not implemented.
- The SACHET polygon endpoint has returned HTTP 403 in the current environment. Alerts without confirmed geographic matching must remain visibly unverified.
- Weather is contextual information, not an official disaster warning.
- No absence of alerts or facilities proves an area is safe. Call 112 in India and follow official responder instructions.

## Native Android map configuration

Expo Go includes the React Native Maps module for foreground testing. A standalone Android development or release build needs a Google Maps Android API key configured in the native Expo config before building. Do not commit the key to a public repository; use an appropriate local environment or build secret. Background location also requires a native development build and OS permission approval.
