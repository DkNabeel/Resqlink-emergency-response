import * as Location from "expo-location";
import * as Notifications from "expo-notifications";
import * as SQLite from "expo-sqlite";
import * as TaskManager from "expo-task-manager";

const LOCATION_TASK = "RESQLINK_BACKGROUND_LOCATION";
const API_BASE_URL = (process.env.EXPO_PUBLIC_API_BASE_URL ?? "").replace(/\\/+$/, "");
const DB_NAME = "resqlink-mobile.db";
const ALERT_CHANNEL = "resqlink-emergency-alerts";

type OfflinePackage = {
  generated_at?: string;
  language?: string;
  location?: { latitude?: number; longitude?: number };
  location_matched_official_alerts?: Array<{ alert_id?: string; title?: string; event?: string; severity?: string }>;
  nearby_verified_facilities?: unknown[];
  nearby_discovered_facilities?: unknown[];
};

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

async function database() {
  if (!dbPromise) {
    dbPromise = SQLite.openDatabaseAsync(DB_NAME).then(async (db) => {
      await db.execAsync(
        "CREATE TABLE IF NOT EXISTS offline_packages (" +
          "cache_key TEXT PRIMARY KEY, etag TEXT, payload_json TEXT NOT NULL, stored_at TEXT NOT NULL" +
          ");" +
          "CREATE TABLE IF NOT EXISTS app_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL);" +
          "CREATE TABLE IF NOT EXISTS notified_alerts (alert_id TEXT PRIMARY KEY, notified_at TEXT NOT NULL);"
      );
      return db;
    });
  }
  return dbPromise;
}

async function getDeviceId(db: SQLite.SQLiteDatabase) {
  const row = await db.getFirstAsync<{ setting_value: string }>(
    "SELECT setting_value FROM app_settings WHERE setting_key = 'device_id'"
  );
  if (row?.setting_value) return row.setting_value;
  const id = "resqlink-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
  await db.runAsync(
    "INSERT OR REPLACE INTO app_settings (setting_key, setting_value) VALUES ('device_id', ?)",
    id
  );
  return id;
}

export async function setBackgroundLanguage(language: string) {
  const db = await database();
  await db.runAsync(
    "INSERT OR REPLACE INTO app_settings (setting_key, setting_value) VALUES ('language', ?)",
    language
  );
}

async function getBackgroundLanguage(db: SQLite.SQLiteDatabase) {
  const row = await db.getFirstAsync<{ setting_value: string }>(
    "SELECT setting_value FROM app_settings WHERE setting_key = 'language'"
  );
  return row?.setting_value === "hi" || row?.setting_value === "kn" ? row.setting_value : "en";
}

async function refreshPackageForLocation(
  db: SQLite.SQLiteDatabase,
  latitude: number,
  longitude: number,
  locality: { city?: string; district?: string; state?: string } = {}
) {
  if (!API_BASE_URL) return;
  const language = await getBackgroundLanguage(db);
  const query = new URLSearchParams({
    latitude: String(latitude),
    longitude: String(longitude),
    language,
    radius_km: "10",
    ...(locality.city ? { city: locality.city } : {}),
    ...(locality.district ? { district: locality.district } : {}),
    ...(locality.state ? { state: locality.state } : {}),
  });
  const response = await fetch(API_BASE_URL + "/offline/package?" + query.toString(), {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) return;

  const payload = (await response.json()) as OfflinePackage;
  const etag = response.headers.get("ETag");
  const storedAt = new Date().toISOString();
  await db.runAsync(
    "INSERT INTO offline_packages (cache_key, etag, payload_json, stored_at) VALUES ('background-latest', ?, ?, ?) " +
      "ON CONFLICT(cache_key) DO UPDATE SET etag = excluded.etag, payload_json = excluded.payload_json, stored_at = excluded.stored_at",
    etag,
    JSON.stringify(payload),
    storedAt
  );
  // Replace stale area data only after the new package was fetched and stored.
  await db.runAsync("DELETE FROM offline_packages WHERE cache_key != 'background-latest'");

  const notificationPermissions = await Notifications.getPermissionsAsync();
  if (!notificationPermissions.granted) return;

  const alerts = payload.location_matched_official_alerts ?? [];
  for (const alert of alerts) {
    const alertId = alert.alert_id;
    if (!alertId) continue;
    const existing = await db.getFirstAsync<{ alert_id: string }>(
      "SELECT alert_id FROM notified_alerts WHERE alert_id = ?",
      alertId
    );
    if (existing) continue;
    await Notifications.scheduleNotificationAsync({
      content: {
        title: "ResQLink · Government disaster alert",
        body: (alert.title || alert.event || "An official alert matches your saved location.").slice(0, 220),
        sound: "default",
        priority: Notifications.AndroidNotificationPriority.MAX,
        channelId: ALERT_CHANNEL,
        data: { alertId, source: "SACHET" },
      },
      trigger: null,
    });
    await db.runAsync(
      "INSERT OR IGNORE INTO notified_alerts (alert_id, notified_at) VALUES (?, ?)",
      alertId,
      new Date().toISOString()
    );
  }
}

TaskManager.defineTask(LOCATION_TASK, async ({ data, error }) => {
  if (error || !data) return;
  const locations = (data as { locations?: Location.LocationObject[] }).locations ?? [];
  const latest = locations[locations.length - 1];
  if (!latest?.coords) return;

  try {
    const db = await database();
    const { latitude, longitude, accuracy } = latest.coords;
    const deviceId = await getDeviceId(db);
    let locality: { city?: string; district?: string; state?: string } = {};
    try {
      const addresses = await Location.reverseGeocodeAsync({ latitude, longitude });
      const address = addresses[0];
      if (address) {
        locality = {
          city: address.city ?? address.subregion ?? undefined,
          district: address.district ?? address.subregion ?? address.city ?? undefined,
          state: address.region ?? undefined,
        };
      }
    } catch {
      // Reverse geocoding is optional; coordinates are still saved.
    }

    // Keep the most recent location locally even if the backend is unreachable.
    await db.runAsync(
      "CREATE TABLE IF NOT EXISTS location_snapshots (" +
        "snapshot_id INTEGER PRIMARY KEY CHECK (snapshot_id = 1), latitude REAL NOT NULL, " +
        "longitude REAL NOT NULL, accuracy_m REAL, recorded_at TEXT NOT NULL)"
    );
    await db.runAsync(
      "INSERT OR REPLACE INTO location_snapshots (snapshot_id, latitude, longitude, accuracy_m, recorded_at) VALUES (1, ?, ?, ?, ?)",
      latitude,
      longitude,
      accuracy ?? null,
      latest.timestamp ? new Date(latest.timestamp).toISOString() : new Date().toISOString()
    );

    if (API_BASE_URL) {
      await fetch(API_BASE_URL + "/locations/resolve", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: deviceId,
          latitude,
          longitude,
          accuracy_m: accuracy ?? null,
          source: "gps",
          city: locality.city,
          district: locality.district,
          state: locality.state,
          country: "India",
        }),
      }).catch(() => null);
      await refreshPackageForLocation(db, latitude, longitude, locality).catch(() => null);
    }
  } catch {
    // Background tasks must fail quietly; the last successfully cached package remains usable.
  }
});

export async function startBackgroundMonitoring(): Promise<{
  locationEnabled: boolean;
  notificationsEnabled: boolean;
  message: string;
}> {
  const foreground = await Location.requestForegroundPermissionsAsync();
  if (foreground.status !== "granted") {
    return {
      locationEnabled: false,
      notificationsEnabled: false,
      message: "Location permission is needed for location-based emergency alerts.",
    };
  }

  const background = await Location.requestBackgroundPermissionsAsync();
  const notificationPermission = await Notifications.requestPermissionsAsync();
  const notificationsEnabled = notificationPermission.granted;

  await Notifications.setNotificationChannelAsync(ALERT_CHANNEL, {
    name: "Emergency alerts",
    importance: Notifications.AndroidImportance.MAX,
    vibrationPattern: [0, 500, 250, 500],
    sound: "default",
    enableVibrate: true,
  });

  if (background.status !== "granted") {
    return {
      locationEnabled: false,
      notificationsEnabled,
      message: "Allow background location to keep the offline area package refreshed. Foreground emergency help remains available.",
    };
  }

  const alreadyStarted = await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK);
  if (!alreadyStarted) {
    await Location.startLocationUpdatesAsync(LOCATION_TASK, {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: 600000,
      distanceInterval: 100,
      deferredUpdatesInterval: 600000,
      deferredUpdatesDistance: 100,
      pausesUpdatesAutomatically: true,
      showsBackgroundLocationIndicator: true,
      foregroundService: {
        notificationTitle: "ResQLink location protection is active",
        notificationBody: "Refreshing your nearby emergency information when the device allows.",
        notificationColor: "#147A6A",
      },
    });
  }

  return {
    locationEnabled: true,
    notificationsEnabled,
    message: notificationsEnabled
      ? "Background location monitoring enabled. Refresh timing is controlled by the phone's operating system."
      : "Background location is enabled, but notification permission is off.",
  };
}
