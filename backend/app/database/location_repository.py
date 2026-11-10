from datetime import datetime, timezone

from app.database.connection import get_connection


def save_location(
    *,
    device_id,
    latitude,
    longitude,
    source,
    accuracy_m=None,
    city=None,
    district=None,
    state=None,
    country=None,
    recorded_at=None,
):
    recorded_at = recorded_at or datetime.now(timezone.utc).isoformat()
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO location_history (
                device_id, latitude, longitude, source, accuracy_m,
                city, district, state, country, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                latitude,
                longitude,
                source,
                accuracy_m,
                city,
                district,
                state,
                country,
                recorded_at,
            ),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def get_last_location(device_id, source=None):
    connection = get_connection()
    try:
        if source:
            row = connection.execute(
                """
                SELECT * FROM location_history
                WHERE device_id = ? AND source = ?
                ORDER BY recorded_at DESC, id DESC LIMIT 1
                """,
                (device_id, source),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT * FROM location_history
                WHERE device_id = ?
                ORDER BY recorded_at DESC, id DESC LIMIT 1
                """,
                (device_id,),
            ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()
