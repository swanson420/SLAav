"""
Database connection dependency for FastAPI endpoints.
"""

import os
import psycopg2
from fastapi import HTTPException


def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL is not set. Enable Postgres in Replit's Database tool."
        )
    conn = psycopg2.connect(database_url)
    try:
        yield conn
    finally:
        conn.close()
