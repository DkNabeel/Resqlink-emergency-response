# ResQLink Mobile (Expo React Native)

This is the first Android/iOS client foundation. It includes:
- Foreground GPS permission and current location retrieval.
- Emergency submission to the FastAPI backend.
- English, Hindi and Kannada selection.
- Download and conditional refresh of the location-scoped offline package.
- Persistent local SQLite cache using expo-sqlite.
- Basic offline keyword guidance from the last saved package plus 112.

## Requirements

- Node.js 22.13 or newer for Expo SDK 58.
- Android phone with Expo Go compatible with SDK 58, or an Android development build.
- Laptop and phone on the same Wi-Fi for a local backend connection.

## Configure the backend address

Copy .env.example to .env and set EXPO_PUBLIC_API_BASE_URL to your laptop's LAN IPv4 address. Do not use 127.0.0.1 from the phone; that points to the phone itself.

Example (replace the address with the laptop's actual IPv4):

EXPO_PUBLIC_API_BASE_URL=http://192.168.1.20:8000

Start FastAPI so other devices on the LAN can reach it:

~~~powershell
cd D:\PROJECTS\Resqlink-emergency-response\backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
~~~

Allow TCP port 8000 through Windows Defender Firewall on the private network if prompted. Do not expose the development server to public networks.

## Install and run

~~~powershell
cd D:\PROJECTS\Resqlink-emergency-response\mobile
npm install
npx expo start
~~~

Scan the QR code with the compatible Expo Go app or run an Android emulator. If installed SDK package versions differ, use npx expo install --fix to align Expo dependencies.

## Offline limits

The phone's SQLite cache stores the most recently fetched package for each rounded coordinate/language key and reuses the ETag on refresh. If the backend is unreachable, the app can show the saved package and basic keyword-matched guidance from that package. This is not full offline NLP, not a downloaded map, and not a replacement for calling 112. No new government alerts, weather or traffic can arrive while disconnected.
