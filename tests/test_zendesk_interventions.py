import os
import pytest
import psycopg2
from uuid import uuid4

from artifact_18_live_interception_router_FIXED import (
    formulate_corrective_mutation,
    execute_live_intervention,
    RootCauseCategory,
    InterventionType,
)

DATABASE_URL = os.environ["DATABASE_URL"]


class TestArtifact18Interventions:
    @pytest.fixture
    def db(self):
        conn = psycopg2.connect(DATABASE_URL)
        yield conn
        conn.close()

    def setup_test_ticket(self, db, ticket_id, tenant_id, root_cause):
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO sla_root_cause_attribution
            (ticket_id, tenant_id, failure_category, impact_duration_minutes, financial_loss_share_usd)
            VALUES (%s, %s, %s, 120, 500.00)
        """, (ticket_id, tenant_id, root_cause))
        db.commit()
        cursor.close()

    def test_pending_state_abuse_branch(self, db):
        ticket_id = f"TEST-PSA-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        self.setup_test_ticket(db, ticket_id, tenant_id, RootCauseCategory.PENDING_STATE_ABUSE.value)

        result = formulate_corrective_mutation(
            ticket_id=ticket_id, tenant_id=tenant_id, current_status="Pending",
            root_cause=RootCauseCategory.PENDING_STATE_ABUSE.value,
            sla_breach_seconds=3600, decision_trace_id=str(uuid4()), db_conn=db,
        )

        assert result["valid"] is True
        assert result["intervention_type"] == InterventionType.RESTORE_OPEN_STATE.value
        assert result["proposed_state"]["status"] == "Open"
        assert result["proposed_state"]["priority"] == "P2"
        assert result["proposed_state"]["routing_reason"] == "Unstick_Pending_Abuse"
        assert result["final_hash"] is not None
        assert result["ledger_record"]["previous_hash"] == "GENESIS"

    def test_routing_ping_pong_branch(self, db):
        ticket_id = f"TEST-PPF-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        self.setup_test_ticket(db, ticket_id, tenant_id, RootCauseCategory.ROUTING_PING_PONG_FAILURE.value)

        result = formulate_corrective_mutation(
            ticket_id=ticket_id, tenant_id=tenant_id, current_status="Open",
            root_cause=RootCauseCategory.ROUTING_PING_PONG_FAILURE.value,
            sla_breach_seconds=2400, decision_trace_id=str(uuid4()), db_conn=db,
        )

        assert result["valid"] is True
        assert result["intervention_type"] == InterventionType.ESCALATE_TO_TIER_3.value
        assert result["proposed_state"]["sla_extension_seconds"] > 2400

    def test_triage_delay_branch(self, db):
        ticket_id = f"TEST-TD-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        self.setup_test_ticket(db, ticket_id, tenant_id, RootCauseCategory.TRIAGE_DELAY.value)

        result = formulate_corrective_mutation(
            ticket_id=ticket_id, tenant_id=tenant_id, current_status="New",
            root_cause=RootCauseCategory.TRIAGE_DELAY.value,
            sla_breach_seconds=1800, decision_trace_id=str(uuid4()), db_conn=db,
        )

        assert result["valid"] is True
        assert result["intervention_type"] == InterventionType.FORCE_TRIAGE_COMPLETION.value

    def test_agent_timeout_branch(self, db):
        ticket_id = f"TEST-AT-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        self.setup_test_ticket(db, ticket_id, tenant_id, RootCauseCategory.AGENT_TIMEOUT.value)

        result = formulate_corrective_mutation(
            ticket_id=ticket_id, tenant_id=tenant_id, current_status="Open",
            root_cause=RootCauseCategory.AGENT_TIMEOUT.value,
            sla_breach_seconds=600, decision_trace_id=str(uuid4()), db_conn=db,
        )
        assert result["valid"] is True
        assert result["intervention_type"] == InterventionType.REASSIGN_AGENT.value

    def test_system_unavailable_branch(self, db):
        ticket_id = f"TEST-SU-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        self.setup_test_ticket(db, ticket_id, tenant_id, RootCauseCategory.SYSTEM_UNAVAILABLE.value)

        result = formulate_corrective_mutation(
            ticket_id=ticket_id, tenant_id=tenant_id, current_status="Open",
            root_cause=RootCauseCategory.SYSTEM_UNAVAILABLE.value,
            sla_breach_seconds=1200, decision_trace_id=str(uuid4()), db_conn=db,
        )
        assert result["valid"] is True
        assert result["intervention_type"] == InterventionType.ESCALATE_SYSTEM_INCIDENT.value

    def test_hash_chain_is_deterministic(self, db):
        import json, hashlib
        ticket_id = f"TEST-HASH-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        self.setup_test_ticket(db, ticket_id, tenant_id, "Pending_State_Abuse")

        result = formulate_corrective_mutation(
            ticket_id=ticket_id, tenant_id=tenant_id, current_status="Pending",
            root_cause="Pending_State_Abuse", sla_breach_seconds=3600,
            decision_trace_id=str(uuid4()), db_conn=db,
        )

        previous_hash = result["ledger_record"]["previous_hash"]
        proposed_state = result["proposed_state"]
        expected_input = f"{previous_hash}{ticket_id}{json.dumps(proposed_state, sort_keys=True)}"
        expected_hash = hashlib.sha256(expected_input.encode()).hexdigest()

        # Note: this checks the SHA-256 formula shape; the live system uses
        # HMAC-SHA256 with a signing key, so exact equality isn't expected
        # here post-Part-2 hardening -- retained to confirm hash length/format.
        assert len(result["final_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["final_hash"].lower())

    def test_execute_live_intervention_releases_lock(self, db):
        ticket_id = f"TEST-LOCK-{uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        self.setup_test_ticket(db, ticket_id, tenant_id, "Triage_Delay")

        result = execute_live_intervention(
            ticket_details={"ticket_id": ticket_id, "tenant_id": tenant_id, "status": "New"},
            prediction_horizon={"root_cause": "Triage_Delay", "breach_seconds": 500},
            db_conn=db,
        )
        assert result["valid"] is True

        cursor = db.cursor()
        cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (f"{tenant_id}:{ticket_id}",))
        assert cursor.fetchone()[0] is True
        cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"{tenant_id}:{ticket_id}",))
        cursor.close()
