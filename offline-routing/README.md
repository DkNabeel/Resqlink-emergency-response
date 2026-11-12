# ResQLink offline road routing (Windows)

ResQLink can calculate road distance, estimated drive time and route geometry without internet by running OSRM locally on the laptop. The phone continues to call the FastAPI backend over the phone hotspot/local Wi-Fi; FastAPI calls OSRM at http://127.0.0.1:5000. No HeiGIT request is needed when local routing is preferred.

## 1. Download only the area you need

1. Open the [BBBike custom OSM extract service](https://extract.bbbike.org/).
2. Move the map to your service area, select **Create**, and resize the box or make a polygon.
3. Include the entire area in which ResQLink must find facilities and routes, with a buffer around the outer edge. If you search facilities out to 20 km, do not make the extract only a 20 km circle; roads should extend beyond the edge so routes can reach facilities near that boundary.
4. Choose **PBF** as the format, give the extract a name, and submit it. BBBike sends a download link when the custom extract is ready. Its help page says extracts are refreshed daily and that "nobody" can be entered instead of an email; the generated extract can then be found on its status page.
5. Download the .osm.pbf file to your laptop.

Use a regional/custom extract rather than the full India extract. A larger extract covers more places but takes more storage, memory and preprocessing time.

## 2. Build the local driving graph

Requirements:
- Docker Desktop installed and running.
- Enough free disk space for the source PBF and generated OSRM graph files. Keep the data folder on an SSD.
- A custom .osm.pbf extract from step 1.

Open PowerShell at the repository root and run:

~~~powershell
.\offline-routing\setup-osrm.ps1 -PbfPath "C:\Users\YOUR_USER\Downloads\your-area.osm.pbf"
~~~

The script copies the extract into offline-routing/data/, downloads the official OSRM container image, builds the car-routing graph, partitions/customizes it with OSRM's recommended MLD pipeline, and starts a local service on port 5000.

The first graph build can take a while depending on the size of your extract. Do not interrupt it. Generated map/graph files are ignored by Git and are not uploaded to the repository.

Check the service:

~~~powershell
docker ps
docker logs --tail 30 resqlink-osrm
Test-NetConnection 127.0.0.1 -Port 5000
~~~

## 3. Enable local-first routing in FastAPI

Add these settings to backend/.env:

~~~env
OFFLINE_ROUTING_URL=http://127.0.0.1:5000
ROUTING_PREFER_LOCAL=true
~~~

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
