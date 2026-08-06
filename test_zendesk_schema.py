import os
import pytest
import psycopg2
from uuid import uuid4

DATABASE_URL = os.environ["DATABASE_URL"]


class TestDatabaseSchema:
    @pytest.fixture
    def db(self):
        conn = psycopg2.connect(DATABASE_URL)
        yield conn
        conn.close()

    def test_artifact_13_schema_exists(self, db):
        cursor = db.cursor()
        required_tables = [
            "canonical_event_log",
            "event_lineage_chain",
            "consistency_quarantine",
            "sla_root_cause_attribution",
            "cfo_financial_leakage_cache",
            "coo_root_cause_attribution_cache",
        ]
        for table in required_tables:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = %s
                )
            """, (table,))
            assert cursor.fetchone()[0], f"Table {table} not found in schema"
        cursor.close()

    def test_artifact_13_sla_root_cause_table_schema(self, db):
        cursor = db.cursor()
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'sla_root_cause_attribution'
            ORDER BY ordinal_position
        """)
        columns = {row[0]: row[1] for row in cursor.fetchall()}
        expected_columns = {
            "attribution_id": "uuid",
            "ticket_id": "character varying",
            "tenant_id": "character varying",
            "failure_category": "character varying",
            "impact_duration_minutes": "integer",
            "financial_loss_share_usd": "numeric",
        }
        for col, dtype in expected_columns.items():
            assert col in columns, f"Column {col} not found"
            assert columns[col] == dtype, f"Column {col} has wrong type: {columns[col]}"
        cursor.close()

    def test_ledger_is_actually_immutable(self, db):
        cursor = db.cursor()
        ticket_id = f"TEST-IMMUT-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"

        cursor.execute("""
            INSERT INTO canonical_event_log
            (tenant_id, ticket_id, event_type, event_payload, write_origin,
             event_version, previous_hash, current_hash)
            VALUES (%s, %s, 'Open', '{}', 'test', 1, 'GENESIS', %s)
            RETURNING event_id
        """, (tenant_id, ticket_id, "0" * 64))
        event_id = cursor.fetchone()[0]
        db.commit()

        with pytest.raises(psycopg2.errors.RaiseException):
            cursor.execute(
                "UPDATE canonical_event_log SET event_type = 'Closed' WHERE event_id = %s",
                (event_id,)
            )
        db.rollback()

        cursor.execute(
            "SELECT event_type FROM canonical_event_log WHERE event_id = %s",
            (event_id,)
        )
        assert cursor.fetchone()[0] == "Open", "Row was mutated despite immutability trigger"
        cursor.close()