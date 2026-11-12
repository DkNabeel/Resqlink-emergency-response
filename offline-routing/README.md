# ResQLink offline road routing (Windows)

ResQLink can calculate road distance, estimated drive time and route geometry without internet by running OSRM locally on the laptop. The phone continues to call the FastAPI backend over the phone hotspot/local Wi-Fi; FastAPI calls OSRM at http://127.0.0.1:5000. No HeiGIT request is needed when local routing is preferred.

## 1. One-command automatic map download and setup

You do **not** need to visit BBBike, draw an extract, or manually download a PBF.

Requirements:
- Docker Desktop installed and running.
- Internet for the first setup only.
- Enough free disk space for the regional map extract and generated OSRM graph.

Open PowerShell at the repository root and run:

~~~powershell
.\offline-routing\setup-osrm.ps1
~~~

The script automatically:
1. Downloads the latest Southern Zone India OpenStreetMap PBF from Geofabrik (roughly 560 MB in the current listing).
2. Downloads the official MD5 checksum and verifies the map file.
3. Resumes a partial download if the connection is interrupted and the command is run again.
4. Downloads the OSRM Docker image.
5. Builds and starts the local driving-road graph.
6. Writes `OFFLINE_ROUTING_URL` and `ROUTING_PREFER_LOCAL=true` into `backend/.env`, preserving all existing API keys.

The Southern Zone extract is a broad regional dataset, not a small GPS-centred download. It avoids downloading the full India extract, which is currently listed at roughly 1.6 GB. If you already have a custom PBF, you can still pass it explicitly:

~~~powershell
.\offline-routing\setup-osrm.ps1 -PbfPath "C:\Maps\your-area.osm.pbf"
~~~

Use `-Rebuild` only when you deliberately need to regenerate the processed graph. The downloaded PBF and generated graph remain in `offline-routing/data/` and are ignored by Git.

The first graph build can take a while depending on the size of your extract. Do not interrupt it. Generated map/graph files are ignored by Git and are not uploaded to the repository.

Check the service:

~~~powershell
docker ps
docker logs --tail 30 resqlink-osrm
Test-NetConnection 127.0.0.1 -Port 5000
~~~

## 3. Enable local-first routing in FastAPI

The setup script writes these settings into backend/.env automatically. Check that they are present if you already had an older setup.

Restart FastAPI:

~~~powershell
cd backend
py -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
~~~

When local-first is enabled, nearby facility distances use one local OSRM Table request (cached for five minutes), and tapping **Route** uses the local OSRM Route service. If the local graph cannot route a location, FastAPI can fall back to HeiGIT when internet and a valid key are available.

With ROUTING_PREFER_LOCAL=false, HeiGIT is tried first and the local OSRM engine is used only as a fallback.

## 4. Test it with the phone offline

1. Keep the laptop connected to the phone's hotspot/local Wi-Fi.
2. Keep Docker's resqlink-osrm container and FastAPI running on the laptop.
3. Turn off the laptop's internet connection while leaving the phone-to-laptop local network active.
4. In the app, refresh nearby facilities and tap **Route**.

The phone still needs local network access to reach FastAPI. The laptop performs the route calculation using its stored road graph, so there is no cloud routing request. The laptop must stay powered on.

Stop the local router when needed:

~~~powershell
.\offline-routing\stop-osrm.ps1
~~~

The graph stays in offline-routing/data/; starting it again is faster than rebuilding it.

## Important boundaries

- This is offline routing through the laptop's local OSRM server. It is not yet a self-contained routing engine running directly on the phone. A standalone phone-only offline build would need a native mobile routing integration and regional graph storage on the device.
- The current map background/tiles are still provided by the online map layer. Route calculation can work offline while the street basemap itself may not render without connectivity; offline map tiles are a separate feature.
- OSM routing uses the road network snapshot in the downloaded PBF. It does not know about live congestion, temporary road closures, floodwater, fires, blocked bridges or official evacuation orders. Never treat a calculated route as verified safe.
- Give attribution to © OpenStreetMap contributors. OSM data is distributed under the Open Database License (ODbL).
