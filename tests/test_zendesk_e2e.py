import os
import pytest
import psycopg2
import json
from uuid import uuid4
from decimal import Decimal
from datetime import datetime

from artifact_18_live_interception_router_FIXED import formulate_corrective_mutation
from artifact_19_api_layer_CORRECTED import CFOFinancialLeakageResponse

DATABASE_URL = os.environ["DATABASE_URL"]


class TestEndToEndPipeline:
    @pytest.fixture
    def db(self):
        conn = psycopg2.connect(DATABASE_URL)
        yield conn
        conn.close()

    def test_full_pipeline_execution(self, db):
        ticket_id = f"E2E-{uuid4().hex[:8]}"
        tenant_id = "e2e_test_tenant"

        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO sla_root_cause_attribution
            (ticket_id, tenant_id, failure_category, impact_duration_minutes, financial_loss_share_usd)
            VALUES (%s, %s, 'Pending_State_Abuse', 120, 500.00)
        """, (ticket_id, tenant_id))
        db.commit()

        result = formulate_corrective_mutation(
            ticket_id=ticket_id, tenant_id=tenant_id, current_status="Pending",
            root_cause="Pending_State_Abuse", sla_breach_seconds=3600,
            decision_trace_id=str(uuid4()), db_conn=db,
        )
        assert result["valid"] is True

        cursor.execute("""
            SELECT event_id, current_hash, previous_hash, event_version
            FROM canonical_event_log
            WHERE ticket_id = %s AND tenant_id = %s
            ORDER BY event_version ASC
        """, (ticket_id, tenant_id))
        ledger_rows = cursor.fetchall()
        assert len(ledger_rows) > 0

        event_id, current_hash, previous_hash, event_version = ledger_rows[0]
        assert previous_hash == "GENESIS"
        assert len(current_hash) == 64

        cfo_response = CFOFinancialLeakageResponse(
            cfo_timestamp=datetime.utcnow(), total_active_breaches=1,
            total_financial_exposure_usd=Decimal("500.00"),
            breaches_by_severity={"P2": 1},
            top_leak_sources=[{"root_cause": "Pending_State_Abuse", "breach_count": 1}],
            view_last_refreshed_at=datetime.utcnow(), freshness_lag_seconds=10,
        )
        response_dict = cfo_response.dict()
        json.dumps(response_dict, default=str)

        cursor.close()
        db.commit()
