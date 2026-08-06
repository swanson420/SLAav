import os
import pytest
import psycopg2
from uuid import uuid4
from decimal import Decimal
from datetime import datetime

from artifact_19_api_layer_CORRECTED import (
    CFOFinancialLeakageResponse,
    COOOperationalAccountingResponse,
    CryptographicProofCertificate,
)
from artifact_19_refresh_strategy_FIXED import PartitionGatedRefreshStrategy
from artifact_18_live_interception_router_FIXED import formulate_corrective_mutation

DATABASE_URL = os.environ["DATABASE_URL"]


class TestArtifact19APIContract:
    def test_cfo_response_schema(self):
        response = CFOFinancialLeakageResponse(
            cfo_timestamp=datetime.utcnow(), total_active_breaches=47,
            total_financial_exposure_usd=Decimal("18750.00"),
            breaches_by_severity={"P0": 12, "P1": 28, "P2": 7}, top_leak_sources=[],
            view_last_refreshed_at=datetime.utcnow(), freshness_lag_seconds=300,
        )
        response_dict = response.dict()
        assert response_dict["freshness_lag_seconds"] == 300

    def test_coo_response_schema(self):
        response = COOOperationalAccountingResponse(
            coo_timestamp=datetime.utcnow(), tickets_analyzed=1247,
            root_cause_breakdown={"Routing_Ping_Pong_Failure": 342},
            average_time_in_pending_minutes=65.3, triage_completion_rate_percent=87.2,
            view_last_refreshed_at=datetime.utcnow(), freshness_lag_seconds=300,
        )
        response_dict = response.dict()
        assert "view_last_refreshed_at" in response_dict

    def test_certificate_uses_renamed_field(self):
        cert = CryptographicProofCertificate(
            ticket_id="ZEN-12345", tenant_id="customer-abc", elapsed_breach_minutes=480,
            active_duration_minutes=520, financial_liability_usd=Decimal("2400.00"),
            cryptographic_proof_signature="a7f3e2d1b9c8f4e5" + "0" * 48,
            proof_timestamp=datetime.utcnow(), audit_trail_complete=True,
        )
        cert_dict = cert.dict()
        assert cert_dict["elapsed_breach_minutes"] == 480


class TestArtifact19RefreshStrategy:
    @pytest.fixture
    def db(self):
        conn = psycopg2.connect(DATABASE_URL)
        yield conn
        conn.close()

    def test_billing_window(self):
        strategy = PartitionGatedRefreshStrategy(db_url="postgresql://unused")
        window_start, window_end = strategy.get_active_billing_window()
        assert window_start < strategy.current_month
        assert window_end > strategy.current_month

    def test_refresh_populates_cfo_cache(self, db):
        ticket_id = f"TEST-REFRESH-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"

        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO sla_root_cause_attribution
            (ticket_id, tenant_id, failure_category, impact_duration_minutes, financial_loss_share_usd)
            VALUES (%s, %s, 'Triage_Delay', 90, 250.00)
        """, (ticket_id, tenant_id))
        db.commit()

        result = formulate_corrective_mutation(
            ticket_id=ticket_id, tenant_id=tenant_id, current_status="New",
            root_cause="Triage_Delay", sla_breach_seconds=500,
            decision_trace_id=str(uuid4()), db_conn=db,
        )
        assert result["valid"] is True

        strategy = PartitionGatedRefreshStrategy(DATABASE_URL)
        strategy.execute_incremental_refresh()

        cursor.execute("""
            SELECT elapsed_breach_minutes, financial_loss_share_usd, cryptographic_proof_signature
            FROM cfo_financial_leakage_cache
            WHERE ticket_id = %s AND tenant_id = %s
        """, (ticket_id, tenant_id))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 90
        assert row[2] == result["final_hash"]
        cursor.close()

    def test_refresh_populates_coo_cache(self, db):
        ticket_id = f"TEST-REFRESH-COO-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"

        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO sla_root_cause_attribution
            (ticket_id, tenant_id, failure_category, impact_duration_minutes, financial_loss_share_usd)
            VALUES (%s, %s, 'Pending_State_Abuse', 45, 100.00)
        """, (ticket_id, tenant_id))
        db.commit()

        strategy = PartitionGatedRefreshStrategy(DATABASE_URL)
        strategy.execute_incremental_refresh()

        cursor.execute("""
            SELECT failure_category, impact_duration_minutes
            FROM coo_root_cause_attribution_cache
            WHERE ticket_id = %s AND tenant_id = %s
        """, (ticket_id, tenant_id))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "Pending_State_Abuse"
        assert row[1] == 45
        cursor.close()
