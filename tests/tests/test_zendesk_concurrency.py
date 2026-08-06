"""
Concurrency test: proves the pg_advisory_lock in execute_live_intervention
actually serializes concurrent writes to the same ticket.
"""

import os
import threading
import psycopg2
from uuid import uuid4

from artifact_18_live_interception_router_FIXED import execute_live_intervention

DATABASE_URL = os.environ["DATABASE_URL"]
CONCURRENCY_LEVEL = 5


def test_concurrent_interventions_on_same_ticket_serialize_correctly():
    ticket_id = f"TEST-CONCURRENT-{uuid4().hex[:8]}"
    tenant_id = "test_tenant"

    setup_conn = psycopg2.connect(DATABASE_URL)
    setup_cursor = setup_conn.cursor()
    setup_cursor.execute("""
        INSERT INTO sla_root_cause_attribution
        (ticket_id, tenant_id, failure_category, impact_duration_minutes, financial_loss_share_usd)
        VALUES (%s, %s, 'Triage_Delay', 60, 200.00)
    """, (ticket_id, tenant_id))
    setup_conn.commit()
    setup_cursor.close()
    setup_conn.close()

    barrier = threading.Barrier(CONCURRENCY_LEVEL)
    results = [None] * CONCURRENCY_LEVEL
    errors = [None] * CONCURRENCY_LEVEL

    def worker(index):
        conn = psycopg2.connect(DATABASE_URL)
        try:
            barrier.wait()
            result = execute_live_intervention(
                ticket_details={"ticket_id": ticket_id, "tenant_id": tenant_id, "status": "New"},
                prediction_horizon={"root_cause": "Triage_Delay", "breach_seconds": 300},
                db_conn=conn,
            )
            results[index] = result
        except Exception as e:
            errors[index] = str(e)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(CONCURRENCY_LEVEL)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert all(e is None for e in errors), f"Threads raised exceptions: {errors}"
    assert all(r is not None for r in results), "Not all threads completed"
    assert all(r["valid"] is True for r in results), f"Some interventions failed: {results}"

    verify_conn = psycopg2.connect(DATABASE_URL)
    verify_cursor = verify_conn.cursor()
    verify_cursor.execute("""
        SELECT event_sequence_index, current_hash, previous_hash
        FROM event_lineage_chain
        WHERE ticket_id = %s AND tenant_id = %s
        ORDER BY event_sequence_index ASC
    """, (ticket_id, tenant_id))
    rows = verify_cursor.fetchall()
    verify_cursor.close()
    verify_conn.close()

    assert len(rows) == CONCURRENCY_LEVEL
    sequence_numbers = [row[0] for row in rows]
    assert sequence_numbers == list(range(1, CONCURRENCY_LEVEL + 1))

    expected_previous = "GENESIS"
    for seq, current_hash, previous_hash in rows:
        assert previous_hash == expected_previous
        expected_previous = current_hash


def test_concurrent_interventions_on_different_tickets_do_not_block_each_other():
    tenant_id = "test_tenant"
    ticket_ids = [f"TEST-PARALLEL-{uuid4().hex[:8]}" for _ in range(3)]

    setup_conn = psycopg2.connect(DATABASE_URL)
    setup_cursor = setup_conn.cursor()
    for tid in ticket_ids:
        setup_cursor.execute("""
            INSERT INTO sla_root_cause_attribution
            (ticket_id, tenant_id, failure_category, impact_duration_minutes, financial_loss_share_usd)
            VALUES (%s, %s, 'Agent_Timeout', 30, 100.00)
        """, (tid, tenant_id))
    setup_conn.commit()
    setup_cursor.close()
    setup_conn.close()

    results = {}

    def worker(tid):
        conn = psycopg2.connect(DATABASE_URL)
        try:
            result = execute_live_intervention(
                ticket_details={"ticket_id": tid, "tenant_id": tenant_id, "status": "Open"},
                prediction_horizon={"root_cause": "Agent_Timeout", "breach_seconds": 100},
                db_conn=conn,
            )
            results[tid] = result
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in ticket_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(results) == len(ticket_ids)
    for tid in ticket_ids:
        assert results[tid]["valid"] is True
        assert results[tid]["ledger_record"]["previous_hash"] == "GENESIS"
