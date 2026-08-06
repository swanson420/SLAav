"""
Artifact 19: Partition-Gated Refresh Strategy (FINAL)
"""

import psycopg2
from datetime import datetime, timedelta


class PartitionGatedRefreshStrategy:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.current_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        self.previous_month = (self.current_month - timedelta(days=1)).replace(day=1)

    def get_active_billing_window(self):
        window_start = self.previous_month
        window_end = (self.current_month + timedelta(days=32)).replace(day=1)
        return window_start, window_end

    def execute_incremental_refresh(self):
        window_start, window_end = self.get_active_billing_window()
        conn = psycopg2.connect(self.db_url)
        try:
            self._refresh_cfo_cache(conn, window_start, window_end)
            self._refresh_coo_cache(conn, window_start, window_end)
            print(f"Incremental refresh completed: {window_start} to {window_end}")
        except Exception as e:
            conn.rollback()
            print(f"Refresh failed: {e}")
            raise
        finally:
            conn.close()

    def _refresh_cfo_cache(self, conn, window_start, window_end):
        cur = conn.cursor()
        try:
            cur.execute("""
                WITH final_event_hashes AS (
                    SELECT el.ticket_id, el.tenant_id, el.event_sequence_index, el.current_hash,
                        ROW_NUMBER() OVER (PARTITION BY el.ticket_id ORDER BY el.event_sequence_index DESC) AS rank
                    FROM event_lineage_chain el
                ),
                final_events_only AS (
                    SELECT ticket_id, tenant_id, event_sequence_index, current_hash
                    FROM final_event_hashes WHERE rank = 1
                )
                INSERT INTO cfo_financial_leakage_cache
                    (ticket_id, tenant_id, cryptographic_proof_signature,
                     active_duration_minutes, financial_loss_share_usd,
                     elapsed_breach_minutes, view_snapshot_timestamp)
                SELECT
                    fe.ticket_id, fe.tenant_id, fe.current_hash,
                    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - ce.timestamp)) / 60,
                    src.financial_loss_share_usd, src.impact_duration_minutes,
                    CURRENT_TIMESTAMP
                FROM final_events_only fe
                JOIN sla_root_cause_attribution src ON src.ticket_id = fe.ticket_id
                LEFT JOIN canonical_event_log ce
                    ON ce.ticket_id = fe.ticket_id AND ce.event_version = fe.event_sequence_index
                WHERE src.attribution_timestamp >= %s AND src.attribution_timestamp < %s
                ON CONFLICT (ticket_id, tenant_id) DO UPDATE SET
                    cryptographic_proof_signature = EXCLUDED.cryptographic_proof_signature,
                    active_duration_minutes = EXCLUDED.active_duration_minutes,
                    financial_loss_share_usd = EXCLUDED.financial_loss_share_usd,
                    elapsed_breach_minutes = EXCLUDED.elapsed_breach_minutes,
                    view_snapshot_timestamp = EXCLUDED.view_snapshot_timestamp;
            """, (window_start, window_end))
            conn.commit()
        finally:
            cur.close()

    def _refresh_coo_cache(self, conn, window_start, window_end):
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO coo_root_cause_attribution_cache
                    (ticket_id, tenant_id, failure_category, impact_duration_minutes,
                     financial_loss_share_usd, attribution_timestamp, view_snapshot_timestamp)
                SELECT ticket_id, tenant_id, failure_category, impact_duration_minutes,
                    financial_loss_share_usd, attribution_timestamp, CURRENT_TIMESTAMP
                FROM sla_root_cause_attribution
                WHERE attribution_timestamp >= %s AND attribution_timestamp < %s
                ON CONFLICT (ticket_id, tenant_id) DO UPDATE SET
                    failure_category = EXCLUDED.failure_category,
                    impact_duration_minutes = EXCLUDED.impact_duration_minutes,
                    financial_loss_share_usd = EXCLUDED.financial_loss_share_usd,
                    attribution_timestamp = EXCLUDED.attribution_timestamp,
                    view_snapshot_timestamp = EXCLUDED.view_snapshot_timestamp;
            """, (window_start, window_end))
            conn.commit()
        finally:
            cur.close()


def scheduled_refresh_job(db_url: str):
    strategy = PartitionGatedRefreshStrategy(db_url)
    strategy.execute_incremental_refresh()


if __name__ == "__main__":
    import os
    scheduled_refresh_job(os.environ["DATABASE_URL"])
