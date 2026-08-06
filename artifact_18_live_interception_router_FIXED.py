"""
ARTIFACT 18: Live Interception Router (FINAL — HMAC-signed hash chain)
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from uuid import uuid4
from enum import Enum
from typing import Dict, Any, Optional, Tuple

from authority_secrets import get_signing_key


class RootCauseCategory(Enum):
    ROUTING_PING_PONG_FAILURE = "Routing_Ping_Pong_Failure"
    PENDING_STATE_ABUSE = "Pending_State_Abuse"
    TRIAGE_DELAY = "Triage_Delay"
    AGENT_TIMEOUT = "Agent_Timeout"
    SYSTEM_UNAVAILABLE = "System_Unavailable"


class InterventionType(Enum):
    ESCALATE_TO_TIER_3 = "Escalate_To_Tier_3"
    RESTORE_OPEN_STATE = "Restore_Open_State"
    FORCE_TRIAGE_COMPLETION = "Force_Triage_Completion"
    EXTEND_SLA_WINDOW = "Extend_SLA_Window"
    REASSIGN_AGENT = "Reassign_Agent"
    ESCALATE_SYSTEM_INCIDENT = "Escalate_System_Incident"


_BASE_SLA_EXTENSION_SECONDS = 1800


def formulate_corrective_mutation(
    ticket_id: str,
    tenant_id: str,
    current_status: str,
    root_cause: str,
    sla_breach_seconds: int,
    decision_trace_id: str,
    db_conn,
) -> Dict[str, Any]:
    def _extension_seconds(multiplier: float = 1.0) -> int:
        return int(_BASE_SLA_EXTENSION_SECONDS + max(0, sla_breach_seconds) * multiplier)

    try:
        cursor = db_conn.cursor()

        cursor.execute("""
            SELECT event_version, current_hash
            FROM event_lineage_chain
            WHERE ticket_id = %s AND tenant_id = %s
            ORDER BY event_sequence_index DESC
            LIMIT 1
        """, (ticket_id, tenant_id))

        row = cursor.fetchone()
        if row:
            current_version = row[0] + 1
            previous_hash = row[1]
        else:
            current_version = 1
            previous_hash = "GENESIS"

        intervention_type = None
        proposed_state = {}

        if root_cause == RootCauseCategory.ROUTING_PING_PONG_FAILURE.value:
            intervention_type = InterventionType.ESCALATE_TO_TIER_3.value
            proposed_state = {
                "ticket_id": ticket_id, "status": "Open", "priority": "P0",
                "routing_queue": "Tier_3_Escalation_Queue",
                "routing_reason": "Escalate_Ping_Pong_Loop", "assigned_to": None,
                "sla_breach_seconds_observed": sla_breach_seconds,
                "sla_extension_seconds": _extension_seconds(multiplier=1.0),
                "intervention_timestamp": datetime.utcnow().isoformat(),
                "decision_trace_id": decision_trace_id,
            }

        elif root_cause == RootCauseCategory.PENDING_STATE_ABUSE.value:
            intervention_type = InterventionType.RESTORE_OPEN_STATE.value
            proposed_state = {
                "ticket_id": ticket_id, "status": "Open", "priority": "P2",
                "routing_queue": "Default_Triage_Queue",
                "routing_reason": "Unstick_Pending_Abuse", "assigned_to": None,
                "sla_breach_seconds_observed": sla_breach_seconds,
                "sla_reset_active_duration": True, "active_duration_seconds": 0,
                "intervention_timestamp": datetime.utcnow().isoformat(),
                "decision_trace_id": decision_trace_id,
            }

        elif root_cause == RootCauseCategory.TRIAGE_DELAY.value:
            intervention_type = InterventionType.FORCE_TRIAGE_COMPLETION.value
            proposed_state = {
                "ticket_id": ticket_id, "status": "Open", "priority": "P1",
                "routing_queue": "Priority_Triage_Queue",
                "routing_reason": "Force_Complete_Triage", "assigned_to": None,
                "sla_breach_seconds_observed": sla_breach_seconds,
                "sla_extension_seconds": _extension_seconds(multiplier=0.5),
                "intervention_timestamp": datetime.utcnow().isoformat(),
                "decision_trace_id": decision_trace_id,
            }

        elif root_cause == RootCauseCategory.AGENT_TIMEOUT.value:
            intervention_type = InterventionType.REASSIGN_AGENT.value
            proposed_state = {
                "ticket_id": ticket_id, "status": "Open", "priority": "P1",
                "routing_queue": "Default_Triage_Queue",
                "routing_reason": "Reassign_After_Agent_Timeout", "assigned_to": None,
                "sla_breach_seconds_observed": sla_breach_seconds,
                "sla_extension_seconds": _extension_seconds(multiplier=0.5),
                "intervention_timestamp": datetime.utcnow().isoformat(),
                "decision_trace_id": decision_trace_id,
            }

        elif root_cause == RootCauseCategory.SYSTEM_UNAVAILABLE.value:
            intervention_type = InterventionType.ESCALATE_SYSTEM_INCIDENT.value
            proposed_state = {
                "ticket_id": ticket_id, "status": current_status, "priority": "P0",
                "routing_queue": "System_Incident_Queue",
                "routing_reason": "Escalate_System_Unavailable", "assigned_to": None,
                "sla_breach_seconds_observed": sla_breach_seconds,
                "sla_extension_seconds": _extension_seconds(multiplier=2.0),
                "intervention_timestamp": datetime.utcnow().isoformat(),
                "decision_trace_id": decision_trace_id,
            }

        else:
            intervention_type = InterventionType.ESCALATE_TO_TIER_3.value
            proposed_state = {
                "ticket_id": ticket_id, "status": "Open", "priority": "P0",
                "routing_queue": "Tier_3_Escalation_Queue",
                "routing_reason": f"Unknown_Root_Cause_{root_cause}", "assigned_to": None,
                "sla_breach_seconds_observed": sla_breach_seconds,
                "sla_extension_seconds": _extension_seconds(multiplier=1.0),
                "intervention_timestamp": datetime.utcnow().isoformat(),
                "decision_trace_id": decision_trace_id,
            }

        hash_input = f"{previous_hash}{ticket_id}{json.dumps(proposed_state, sort_keys=True)}"
        signing_key = get_signing_key().encode()
        final_hash = hmac.new(signing_key, hash_input.encode(), hashlib.sha256).hexdigest()

        ledger_record = {
            "event_id": str(uuid4()), "tenant_id": tenant_id, "ticket_id": ticket_id,
            "event_type": proposed_state.get("status", current_status),
            "timestamp": datetime.utcnow().isoformat(), "event_payload": proposed_state,
            "write_origin": "Artifact_18_Live_Interception_Router",
            "decision_trace_id": decision_trace_id, "event_version": current_version,
            "previous_hash": previous_hash, "current_hash": final_hash,
        }

        cursor.execute("""
            INSERT INTO canonical_event_log
            (tenant_id, ticket_id, event_type, event_payload, write_origin,
             decision_trace_id, event_version, previous_hash, current_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            tenant_id, ticket_id, proposed_state.get("status", current_status),
            json.dumps(proposed_state), ledger_record["write_origin"],
            decision_trace_id, current_version, previous_hash, final_hash,
        ))

        cursor.execute("""
            INSERT INTO event_lineage_chain
            (ticket_id, tenant_id, event_sequence_index, event_version,
             current_hash, previous_hash)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (ticket_id, tenant_id, current_version, current_version, final_hash, previous_hash))

        db_conn.commit()

        return {
            "ticket_id": ticket_id, "status": proposed_state.get("status", current_status),
            "valid": True, "issue_count": 0, "issues": [],
            "intervention_type": intervention_type, "proposed_state": proposed_state,
            "ledger_record": ledger_record, "final_hash": final_hash,
            "decision_trace_id": decision_trace_id,
        }

    except Exception as e:
        db_conn.rollback()
        return {
            "ticket_id": ticket_id, "status": current_status, "valid": False,
            "issue_count": 1, "issues": [f"Intervention failed: {str(e)}"],
            "intervention_type": None, "proposed_state": {}, "ledger_record": None,
            "final_hash": None, "decision_trace_id": decision_trace_id,
        }

    finally:
        cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"{tenant_id}:{ticket_id}",))
        cursor.close()


def execute_live_intervention(
    ticket_details: Dict[str, Any],
    prediction_horizon: Dict[str, Any],
    db_conn,
) -> Dict[str, Any]:
    ticket_id = ticket_details["ticket_id"]
    tenant_id = ticket_details["tenant_id"]
    lock_cursor = None

    try:
        lock_cursor = db_conn.cursor()
        lock_cursor.execute(
            "SELECT pg_advisory_lock(hashtext(%s))", (f"{tenant_id}:{ticket_id}",)
        )

        result = formulate_corrective_mutation(
            ticket_id=ticket_id, tenant_id=tenant_id,
            current_status=ticket_details.get("status", "Open"),
            root_cause=prediction_horizon.get("root_cause", "Unknown"),
            sla_breach_seconds=prediction_horizon.get("breach_seconds", 0),
            decision_trace_id=str(uuid4()), db_conn=db_conn,
        )
        return result

    except Exception as e:
        return {
            "ticket_id": ticket_id, "status": "Error", "valid": False,
            "issues": [f"Lock acquisition or execution failed: {str(e)}"],
        }

    finally:
        if lock_cursor is not None:
            lock_cursor.close()
