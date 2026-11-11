from app.database.connection import get_connection


FACILITY_COLUMN_MIGRATIONS = {
    "source_name": "TEXT",
    "verification_status": "TEXT NOT NULL DEFAULT 'unverified'",
    "verification_note": "TEXT",
    "last_verified_at": "TEXT",
}


ALERT_COLUMN_MIGRATIONS = {
    "sender": "TEXT",
    "scope": "TEXT",
    "onset_at": "TEXT",
    "cap_identifier": "TEXT",
    "languages_json": "TEXT NOT NULL DEFAULT '{}'",
    "parameters_json": "TEXT NOT NULL DEFAULT '[]'",
}


def create_tables():
    """Create ResQLink tables and safely add newer alert fields."""
    connection = get_connection()
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS facilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                facility_type TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                address TEXT,
                phone TEXT,
                source_name TEXT,
                verification_status TEXT NOT NULL DEFAULT 'unverified',
                verification_note TEXT,
                last_verified_at TEXT
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                event TEXT,
                category TEXT,
                severity TEXT,
                urgency TEXT,
                certainty TEXT,
                status TEXT NOT NULL DEFAULT 'Unknown',
                message_type TEXT,
                effective_at TEXT,
                expires_at TEXT,
                published_at TEXT,
                area_description TEXT,
                polygons_json TEXT NOT NULL DEFAULT '[]',
                circles_json TEXT NOT NULL DEFAULT '[]',
                geocodes_json TEXT NOT NULL DEFAULT '[]',
                references_json TEXT NOT NULL DEFAULT '[]',
                source_url TEXT,
                raw_content TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                sender TEXT,
                scope TEXT,
                onset_at TEXT,
                cap_identifier TEXT,
                languages_json TEXT NOT NULL DEFAULT '{}',
                parameters_json TEXT NOT NULL DEFAULT '[]'
            )
        """)

        # Add columns to existing databases without deleting any stored records.
        existing_facility_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(facilities)")
        }
        for column, definition in FACILITY_COLUMN_MIGRATIONS.items():
            if column not in existing_facility_columns:
                connection.execute(
                    f"ALTER TABLE facilities ADD COLUMN {column} {definition}"
                )

        existing_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(alerts)")
        }
        for column, definition in ALERT_COLUMN_MIGRATIONS.items():
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE alerts ADD COLUMN {column} {definition}"
                )

        connection.execute("""
            CREATE TABLE IF NOT EXISTS external_document_cache (
                document_url TEXT PRIMARY KEY,
                etag TEXT,
                last_modified TEXT,
                content TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                last_http_status INTEGER
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_expiry
            ON alerts(expires_at)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_published
            ON alerts(published_at)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_status
            ON alerts(status)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS feed_sync_state (
                feed_url TEXT PRIMARY KEY,
                etag TEXT,
                last_modified TEXT,
                last_checked_at TEXT,
                last_success_at TEXT,
                last_http_status INTEGER,
                last_error TEXT
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS location_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                source TEXT NOT NULL,
                accuracy_m REAL,
                city TEXT,
                district TEXT,
                state TEXT,
                country TEXT,
                recorded_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_location_device_time
            ON location_history(device_id, recorded_at DESC)
        """)

        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    create_tables()
    print("ResQLink database tables created or already exist.")
