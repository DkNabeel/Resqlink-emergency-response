from app.database.connection import get_connection


def create_tables():
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
                phone TEXT
            )
        """)
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    create_tables()
    print("Facilities table created or already exists.")