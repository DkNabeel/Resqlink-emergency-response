from datetime import datetime, timezone

from app.database.connection import get_connection


def create_facility(
    name, facility_type, latitude, longitude, address=None, phone=None,
    source_name=None,
):
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO facilities (
                name, facility_type, latitude, longitude, address, phone,
                source_name, verification_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'unverified')
            """,
            (name, facility_type, latitude, longitude, address, phone, source_name),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def get_all_facilities(verification_status=None, facility_type=None, limit=1000):
    connection = get_connection()
    try:
        query = """
            SELECT id, name, facility_type, latitude, longitude, address, phone,
                   source_name, verification_status, verification_note, last_verified_at
            FROM facilities
            WHERE 1 = 1
        """
        params = []
        if verification_status:
            query += " AND verification_status = ?"
            params.append(verification_status)
        if facility_type:
            query += " AND LOWER(facility_type) = LOWER(?)"
            params.append(facility_type)
        query += " ORDER BY name COLLATE NOCASE, id LIMIT ?"
        params.append(limit)
        rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def update_facility(
    facility_id, name, facility_type, latitude, longitude, address=None,
    phone=None, source_name=None,
):
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE facilities
            SET name = ?, facility_type = ?, latitude = ?, longitude = ?,
                address = ?, phone = ?, source_name = ?,
                verification_status = 'unverified',
                verification_note = NULL, last_verified_at = NULL
            WHERE id = ?
            """,
            (
                name, facility_type, latitude, longitude, address, phone,
                source_name, facility_id,
            ),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def set_facility_verification(facility_id, status, note):
    if status not in {"verified", "unverified"}:
        raise ValueError("Verification status must be verified or unverified.")

    verified_at = (
        datetime.now(timezone.utc).isoformat() if status == "verified" else None
    )
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE facilities
            SET verification_status = ?, verification_note = ?, last_verified_at = ?
            WHERE id = ?
            """,
            (status, note, verified_at, facility_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def delete_facility(facility_id):
    connection = get_connection()
    try:
        cursor = connection.execute(
            "DELETE FROM facilities WHERE id = ?",
            (facility_id,),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()
