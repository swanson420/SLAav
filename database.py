"""
Database connection dependency for FastAPI endpoints.
"""

import os
import psycopg2
from fastapi import HTTPException


def _find_database_url():
    """
    Checks a few common environment variable names for the database
    connection string, since different hosts (Replit, Railway, etc.)
    sometimes use different names.
    """
    for var_name in ("DATABASE_URL", "DATABASE_PRIVATE_URL", "DATABASE_PUBLIC_URL"):
        value = os.environ.get(var_name)
        if value:
            return value
    return None


def get_db_connection():
    database_url = _find_database_url()
    if not database_url:
        raise HTTPException(
            status_code=500,
            detail=(
                "No database connection string found. Checked DATABASE_URL, "
                "DATABASE_PRIVATE_URL, and DATABASE_PUBLIC_URL environment "
                "variables — none were set."
            )
        )
    conn = psycopg2.connect(database_url)
    try:
        yield conn
    finally:
        conn.close()