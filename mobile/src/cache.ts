import * as SQLite from "expo-sqlite";
import type { NearbyFacility, OfflinePackage } from "./api";

export type CachedPackage = {
  cacheKey: string;
  etag: string | null;
  payload: OfflinePackage;
  storedAt: string;
};

export type CachedNearbyFacilities = {
  latitude: number;
  longitude: number;
  radiusKm: number;
  items: NearbyFacility[];
  storedAt: string;
};

export type CachedChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export async function saveEmergencyChatHistory(history: CachedChatMessage[]): Promise<void> {
  const db = await database();
  const storedAt = new Date().toISOString();
  const normalized = history
    .filter((item) => (item.role === "user" || item.role === "assistant")
      && typeof item.content === "string" && item.content.trim())
    .slice(-10)
    .map((item) => ({ role: item.role, content: item.content.slice(0, 1600) }));
  await db.runAsync(
    "INSERT INTO emergency_chat_history (id, history_json, stored_at) VALUES (1, ?, ?) " +
      "ON CONFLICT(id) DO UPDATE SET history_json = excluded.history_json, stored_at = excluded.stored_at",
    JSON.stringify(normalized),
    storedAt,
  );
}

export async function clearEmergencyChatHistory(): Promise<void> {
  const db = await database();
  await db.runAsync("DELETE FROM emergency_chat_history WHERE id = 1");
}

export async function getEmergencyChatHistory(): Promise<CachedChatMessage[]> {
  const db = await database();
  const row = await db.getFirstAsync<{ history_json: string }>(
    "SELECT history_json FROM emergency_chat_history WHERE id = 1",
  );
  if (!row) return [];
  try {
    const parsed: unknown = JSON.parse(row.history_json);
    if (!Array.isArray(parsed)) throw new Error("Invalid emergency chat history.");
    return parsed
      .filter((item): item is { role: "user" | "assistant"; content: string } =>
        Boolean(item)
        && typeof item === "object"
        && ((item as { role?: unknown }).role === "user" || (item as { role?: unknown }).role === "assistant")
        && typeof (item as { content?: unknown }).content === "string"
        && Boolean((item as { content: string }).content.trim()))
      .slice(-10)
      .map((item) => ({ role: item.role, content: item.content.slice(0, 1600) }));
  } catch {
    await db.runAsync("DELETE FROM emergency_chat_history WHERE id = 1");
    return [];
  }
}

let databasePromise: Promise<SQLite.SQLiteDatabase> | null = null;

async function database() {
  if (!databasePromise) {
    databasePromise = SQLite.openDatabaseAsync("resqlink-mobile.db").then(async (db) => {
      await db.execAsync(
        "CREATE TABLE IF NOT EXISTS offline_packages (" +
          "cache_key TEXT PRIMARY KEY, " +
          "etag TEXT, " +
          "payload_json TEXT NOT NULL, " +
          "stored_at TEXT NOT NULL" +
          ");" +
          "CREATE TABLE IF NOT EXISTS emergency_chat_history (" +
          "id INTEGER PRIMARY KEY CHECK (id = 1), " +
          "history_json TEXT NOT NULL, " +
          "stored_at TEXT NOT NULL" +
          ");" +
          "CREATE TABLE IF NOT EXISTS nearby_facilities_cache (" +
          "id INTEGER PRIMARY KEY CHECK (id = 1), " +
          "latitude REAL NOT NULL, " +
          "longitude REAL NOT NULL, " +
          "radius_km REAL NOT NULL, " +
          "items_json TEXT NOT NULL, " +
          "stored_at TEXT NOT NULL" +
          ");",
      );
      return db;
    });
  }
  return databasePromise;
}

export async function saveOfflinePackage(
  cacheKey: string,
  etag: string | null,
  payload: OfflinePackage,
): Promise<CachedPackage> {
  const db = await database();
  const storedAt = new Date().toISOString();
  await db.runAsync(
    "INSERT INTO offline_packages (cache_key, etag, payload_json, stored_at) " +
      "VALUES (?, ?, ?, ?) " +
      "ON CONFLICT(cache_key) DO UPDATE SET " +
      "etag = excluded.etag, payload_json = excluded.payload_json, stored_at = excluded.stored_at",
    cacheKey,
    etag,
    JSON.stringify(payload),
    storedAt,
  );
  // Keep only the newest location package so repeated refreshes do not grow
  // the device cache indefinitely.
  await db.runAsync("DELETE FROM offline_packages WHERE cache_key != ?", cacheKey);
  return { cacheKey, etag, payload, storedAt };
}

export async function getCachedPackage(cacheKey: string): Promise<CachedPackage | null> {
  const db = await database();
  const row = await db.getFirstAsync<{
    cache_key: string;
    etag: string | null;
    payload_json: string;
    stored_at: string;
  }>(
    "SELECT cache_key, etag, payload_json, stored_at FROM offline_packages WHERE cache_key = ?",
    cacheKey,
  );
  if (!row) return null;
  try {
    return {
      cacheKey: row.cache_key,
      etag: row.etag,
      payload: JSON.parse(row.payload_json) as OfflinePackage,
      storedAt: row.stored_at,
    };
  } catch {
    await db.runAsync("DELETE FROM offline_packages WHERE cache_key = ?", cacheKey);
    return null;
  }
}

export async function getLatestOfflinePackage(): Promise<CachedPackage | null> {
  const db = await database();
  const row = await db.getFirstAsync<{
    cache_key: string;
    etag: string | null;
    payload_json: string;
    stored_at: string;
  }>(
    "SELECT cache_key, etag, payload_json, stored_at " +
      "FROM offline_packages ORDER BY stored_at DESC LIMIT 1",
  );
  if (!row) return null;
  try {
    return {
      cacheKey: row.cache_key,
      etag: row.etag,
      payload: JSON.parse(row.payload_json) as OfflinePackage,
      storedAt: row.stored_at,
    };
  } catch {
    await db.runAsync("DELETE FROM offline_packages WHERE cache_key = ?", row.cache_key);
    return null;
  }
}


export async function saveNearbyFacilitiesCache(
  latitude: number,
  longitude: number,
  radiusKm: number,
  items: NearbyFacility[],
): Promise<CachedNearbyFacilities> {
  const db = await database();
  const storedAt = new Date().toISOString();
  await db.runAsync(
    "INSERT INTO nearby_facilities_cache (id, latitude, longitude, radius_km, items_json, stored_at) " +
      "VALUES (1, ?, ?, ?, ?, ?) " +
      "ON CONFLICT(id) DO UPDATE SET " +
      "latitude = excluded.latitude, longitude = excluded.longitude, " +
      "radius_km = excluded.radius_km, items_json = excluded.items_json, stored_at = excluded.stored_at",
    latitude,
    longitude,
    radiusKm,
    JSON.stringify(items),
    storedAt,
  );
  return { latitude, longitude, radiusKm, items, storedAt };
}

export async function getNearbyFacilitiesCache(): Promise<CachedNearbyFacilities | null> {
  const db = await database();
  const row = await db.getFirstAsync<{
    latitude: number;
    longitude: number;
    radius_km: number;
    items_json: string;
    stored_at: string;
  }>(
    "SELECT latitude, longitude, radius_km, items_json, stored_at " +
      "FROM nearby_facilities_cache WHERE id = 1",
  );
  if (!row) return null;
  try {
    const items = JSON.parse(row.items_json) as NearbyFacility[];
    if (!Array.isArray(items)) throw new Error("Cached facility list is invalid.");
    return {
      latitude: row.latitude,
      longitude: row.longitude,
      radiusKm: row.radius_km,
      items,
      storedAt: row.stored_at,
    };
  } catch {
    await db.runAsync("DELETE FROM nearby_facilities_cache WHERE id = 1");
    return null;
  }
}
