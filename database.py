import sqlite3
from pathlib import Path


# ===================================================
# DATABASE CONFIGURATION
# ===================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "resq.db"


# ---------------------------------------------------
# GET DATABASE CONNECTION
# ---------------------------------------------------

def get_connection():

    connection = sqlite3.connect(
        DB_PATH,
        timeout=10
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA busy_timeout = 10000"
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    return connection


# ---------------------------------------------------
# CHECK IF COLUMN EXISTS
# ---------------------------------------------------

def column_exists(
    connection,
    table_name,
    column_name
):

    columns = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    for column in columns:

        if column["name"] == column_name:
            return True

    return False


# ===================================================
# INITIALIZE DATABASE
# ===================================================

def init_db():

    connection = get_connection()

    # Better SQLite concurrency
    connection.execute(
        "PRAGMA journal_mode=WAL"
    )

    # Add this inside your init_db() function alongside your other CREATE TABLE statements:
    cursor.execute(
        """
            CREATE TABLE IF NOT EXISTS road_hazards (
            hazard_id TEXT PRIMARY KEY,
            hazard_type TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            radius_meters REAL NOT NULL DEFAULT 100,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """
    )

    # =================================================
    # INCIDENT TABLE
    # =================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (

            incident_id TEXT PRIMARY KEY,

            description TEXT NOT NULL,

            location TEXT NOT NULL,

            disaster_type TEXT NOT NULL,

            people_affected INTEGER NOT NULL,

            vulnerable_people INTEGER NOT NULL,

            injuries INTEGER NOT NULL,

            mobility_issue INTEGER NOT NULL,

            danger_level INTEGER NOT NULL,

            required_resources TEXT NOT NULL,

            status TEXT NOT NULL,

            assigned_team_id TEXT,

            created_at TEXT NOT NULL,

            updated_at TEXT NOT NULL,

            updates TEXT NOT NULL,

            latitude REAL,

            longitude REAL
        )
        """
    )


    # -------------------------------------------------
    # Migration support for older database
    # -------------------------------------------------

    if not column_exists(
        connection,
        "incidents",
        "latitude"
    ):

        connection.execute(
            """
            ALTER TABLE incidents
            ADD COLUMN latitude REAL
            """
        )


    if not column_exists(
        connection,
        "incidents",
        "longitude"
    ):

        connection.execute(
            """
            ALTER TABLE incidents
            ADD COLUMN longitude REAL
            """
        )


    # =================================================
    # RESOURCE TABLE
    # =================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS resources (

            resource_id TEXT PRIMARY KEY,

            name TEXT NOT NULL,

            resource_type TEXT NOT NULL,

            capacity INTEGER NOT NULL,

            capabilities TEXT NOT NULL,

            equipment TEXT NOT NULL,

            location TEXT NOT NULL,

            latitude REAL,

            longitude REAL,

            status TEXT NOT NULL,

            current_assignment TEXT,

            created_at TEXT NOT NULL,

            updated_at TEXT NOT NULL
        )
        """
    )


    # =================================================
    # INCIDENT ↔ RESOURCE ASSIGNMENT TABLE
    # =================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS
        incident_resource_assignments (

            incident_id TEXT NOT NULL,

            resource_id TEXT NOT NULL,

            assigned_at TEXT NOT NULL,

            status TEXT NOT NULL
                DEFAULT 'assigned',

            PRIMARY KEY (
                incident_id,
                resource_id
            ),

            FOREIGN KEY (incident_id)
                REFERENCES incidents(incident_id),

            FOREIGN KEY (resource_id)
                REFERENCES resources(resource_id)
        )
        """
    )


    # Helpful when looking up assignments
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_assignment_incident

        ON incident_resource_assignments(
            incident_id
        )
        """
    )


    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_assignment_resource

        ON incident_resource_assignments(
            resource_id
        )
        """
    )


    connection.commit()
    connection.close()
