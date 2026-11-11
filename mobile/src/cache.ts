import * as SQLite from "expo-sqlite";
import type { OfflinePackage } from "./api";

export type CachedPackage = {
  cacheKey: string;
  etag: string | null;
  payload: OfflinePackage;
  storedAt: string;
};

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
