from app.database.connection import get_connection


def create_facility(name, facility_type, latitude, longitude, address=None, phone=None):
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO facilities
                (name, facility_type, latitude, longitude, address, phone)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, facility_type, latitude, longitude, address, phone)
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def get_all_facilities():
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT id, name, facility_type, latitude, longitude, address, phone
            FROM facilities
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()

def update_facility(facility_id, name, facility_type, latitude, longitude, address=None, phone=None):
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE facilities
            SET name = ?, facility_type = ?, latitude = ?, longitude = ?,
                address = ?, phone = ?
            WHERE id = ?
            """,
            (name, facility_type, latitude, longitude, address, phone, facility_id)
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
            (facility_id,)
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()