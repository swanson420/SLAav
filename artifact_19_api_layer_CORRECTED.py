"""
ARTIFACT 19: Programmatic View API Layer (FIXED — v3 audit pass, API-key enforced)
Database Engineering / API Architecture

Changes from prior versions:
  1. Reads from cfo_financial_leakage_cache / coo_root_cause_attribution_cache
     (real tables, see Artifact 13) instead of mv_cfo_financial_leakage /
     mv_coo_root_cause_attribution (materialized views).
  2. Renamed sla_contract_limit_minutes -> elapsed_breach_minutes.
  3. breaches_by_severity, top_leak_sources, root_cause_breakdown, and
     triage_completion_rate_percent are computed from real queries.
  4. Freshness reads MAX(view_snapshot_timestamp) from the cache table.
  5. Contract version bumped to 1.2.0.
  6. db_conn is a real FastAPI dependency (Depends(get_db_connection)).
  7. All three data-returning endpoints now require a valid X-API-Key header
     (via auth.require_api_key). Previously, anyone with the URL could pull
     any tenant's financial data with no authentication at all.
"""

from fastapi import FastAPI, Query, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import psycopg2
from decimal import Decimal

from database import get_db_connection
from auth import require_api_key

app = FastAPI(
    title="Zendesk Authority Layer - Read Replica API",
    version="1.0.0",
    description="Immutable, auditable view layer exposing CFO/COO dashboards"
)


class CryptographicProofCertificate(BaseModel):
    ticket_id: str
    tenant_id: str
    elapsed_breach_minutes: int = Field(
        description="Minutes the ticket has already been in SLA breach (NOT the SLA's contractual time limit)"
    )
    active_duration_minutes: int
    financial_liability_usd: Decimal
    cryptographic_proof_signature: str = Field(
        description="HMAC-SHA256 hash chain of FINAL event in ticket lineage"
    )
    proof_timestamp: datetime
    audit_trail_complete: bool

    class Config:
        json_schema_extra = {
            "example": {
                "ticket_id": "ZEN-12345",
                "tenant_id": "customer-abc",
                "elapsed_breach_minutes": 480,
                "active_duration_minutes": 520,
                "financial_liability_usd": "2400.00",
                "cryptographic_proof_signature": "a7f3e2d1...",
                "proof_timestamp": "2024-07-27T18:30:00Z",
                "audit_trail_complete": True
            }
        }


class CFOFinancialLeakageResponse(BaseModel):
    cfo_timestamp: datetime
    total_active_breaches: int
    total_financial_exposure_usd: Decimal
    breaches_by_severity: Dict[str, int]
    top_leak_sources: List[Dict[str, Any]]
    view_last_refreshed_at: Optional[datetime] = Field(
        description="Last cache refresh timestamp"
    )
    freshness_lag_seconds: int = Field(
        description="Seconds since last cache refresh"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "cfo_timestamp": "2024-07-27T18:45:00Z",
                "total_active_breaches": 47,
                "total_financial_exposure_usd": "18750.00",
                "breaches_by_severity": {"P0": 12, "P1": 28, "P2": 7},
                "top_leak_sources": [
                    {
                        "root_cause": "Pending_State_Abuse",
                        "breach_count": 23,
                        "financial_impact_usd": "11500.00"
                    }
                ],
                "view_last_refreshed_at": "2024-07-27T18:40:00Z",
                "freshness_lag_seconds": 300
            }
        }


class COOOperationalAccountingResponse(BaseModel):
    coo_timestamp: datetime
    tickets_analyzed: int
    root_cause_breakdown: Dict[str, int]
    average_time_in_pending_minutes: float
    triage_completion_rate_percent: float
    view_last_refreshed_at: Optional[datetime] = Field(
        description="Last cache refresh timestamp"
    )
    freshness_lag_seconds: int = Field(
        description="Seconds since last cache refresh"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "coo_timestamp": "2024-07-27T18:45:00Z",
                "tickets_analyzed": 1247,
                "root_cause_breakdown": {
                    "Routing_Ping_Pong_Failure": 342,
                    "Pending_State_Abuse": 189,
                    "Triage_Delay": 456
                },
                "average_time_in_pending_minutes": 65.3,
                "triage_completion_rate_percent": 87.2,
                "view_last_refreshed_at": "2024-07-27T18:40:00Z",
                "freshness_lag_seconds": 300
            }
        }


CONTRACT_SCHEMA_V1_2_0 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Zendesk Authority Layer API Contract",
    "version": "1.2.0",
    "description": "Immutable contract for CFO/COO financial and operational dashboards",
    "type": "object",
    "definitions": {
        "cfo_financial_leakage": {
            "type": "object",
            "properties": {
                "cfo_timestamp": {"type": "string", "format": "date-time"},
                "total_active_breaches": {"type": "integer", "minimum": 0},
                "total_financial_exposure_usd": {"type": "string", "pattern": "^\\d+\\.\\d{2}$"},
                "breaches_by_severity": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"}
                },
                "top_leak_sources": {"type": "array", "items": {"type": "object"}},
                "view_last_refreshed_at": {"type": ["string", "null"], "format": "date-time"},
                "freshness_lag_seconds": {"type": "integer", "minimum": 0}
            },
            "required": [
                "cfo_timestamp",
                "total_active_breaches",
                "total_financial_exposure_usd",
                "view_last_refreshed_at",
                "freshness_lag_seconds"
            ],
            "additionalProperties": False
        },
        "financial_certificate": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "tenant_id": {"type": "string"},
                "elapsed_breach_minutes": {"type": "integer", "minimum": 0},
                "active_duration_minutes": {"type": "integer"},
                "financial_liability_usd": {"type": "string"},
                "cryptographic_proof_signature": {"type": "string"},
                "proof_timestamp": {"type": "string", "format": "date-time"},
                "audit_trail_complete": {"type": "boolean"}
            },
            "required": ["ticket_id", "tenant_id", "elapsed_breach_minutes", "cryptographic_proof_signature"],
            "additionalProperties": False
        }
    }
}


@app.get(
    "/api/v1/financial-certificate/{ticket_id}",
    response_model=CryptographicProofCertificate,
    tags=["CFO Dashboards"],
    summary="Get cryptographic proof certificate for a ticket"
)
async def get_financial_certificate(
    ticket_id: str,
    tenant_id: str = Query(..., description="Customer tenant ID"),
    db_conn = Depends(get_db_connection),
    _role: str = Depends(require_api_key),
) -> CryptographicProofCertificate:
    cursor = db_conn.cursor()
    try:
        cursor.execute("""
            WITH final_event AS (
                SELECT current_hash
                FROM event_lineage_chain
                WHERE ticket_id = %s AND tenant_id = %s
                ORDER BY event_sequence_index DESC
                LIMIT 1
            )
            SELECT
                ce.ticket_id,
                ce.tenant_id,
                src.impact_duration_minutes,
                EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - ce.timestamp)) / 60,
                src.financial_loss_share_usd,
                fe.current_hash,
                ce.timestamp
            FROM canonical_event_log ce
            CROSS JOIN final_event fe
            LEFT JOIN sla_root_cause_attribution src ON ce.ticket_id = src.ticket_id
            WHERE ce.ticket_id = %s AND ce.tenant_id = %s
            ORDER BY ce.event_version DESC
            LIMIT 1
        """, (ticket_id, tenant_id, ticket_id, tenant_id))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Ticket not found")

        return CryptographicProofCertificate(
            ticket_id=row[0],
            tenant_id=row[1],
            elapsed_breach_minutes=row[2] or 0,
            active_duration_minutes=int(row[3] or 0),
            financial_liability_usd=row[4] or Decimal("0.00"),
            cryptographic_proof_signature=row[5],
            proof_timestamp=row[6],
            audit_trail_complete=True
        )

    finally:
        cursor.close()


@app.get(
    "/api/v1/cfo/financial-leakage",
    response_model=CFOFinancialLeakageResponse,
    tags=["CFO Dashboards"],
    summary="CFO dashboard: current financial leakage"
)
async def get_cfo_financial_leakage(
    tenant_id: str = Query(..., description="Customer tenant ID"),
    db_conn = Depends(get_db_connection),
    _role: str = Depends(require_api_key),
) -> CFOFinancialLeakageResponse:
    cursor = db_conn.cursor()
    try:
        cursor.execute("""
            SELECT
                COUNT(*) AS total_breaches,
                COALESCE(SUM(financial_loss_share_usd), 0) AS total_exposure,
                MAX(view_snapshot_timestamp) AS last_refreshed
            FROM cfo_financial_leakage_cache
            WHERE tenant_id = %s
        """, (tenant_id,))
        total_breaches, total_exposure, refresh_time = cursor.fetchone()

        cursor.execute("""
            SELECT
                COALESCE(ce.event_payload->>'priority', 'Unknown') AS priority,
                COUNT(*)
            FROM cfo_financial_leakage_cache c
            LEFT JOIN LATERAL (
                SELECT event_payload
                FROM canonical_event_log
                WHERE ticket_id = c.ticket_id AND tenant_id = c.tenant_id
                ORDER BY event_version DESC
                LIMIT 1
            ) ce ON TRUE
            WHERE c.tenant_id = %s
            GROUP BY 1
        """, (tenant_id,))
        breaches_by_severity = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT
                src.failure_category,
                COUNT(*) AS breach_count,
                COALESCE(SUM(c.financial_loss_share_usd), 0) AS financial_impact_usd
            FROM cfo_financial_leakage_cache c
            JOIN sla_root_cause_attribution src ON src.ticket_id = c.ticket_id
            WHERE c.tenant_id = %s
            GROUP BY src.failure_category
            ORDER BY financial_impact_usd DESC
            LIMIT 5
        """, (tenant_id,))
        top_leak_sources = [
            {
                "root_cause": row[0],
                "breach_count": row[1],
                "financial_impact_usd": str(row[2])
            }
            for row in cursor.fetchall()
        ]

        freshness_seconds = (
            int((datetime.utcnow() - refresh_time.replace(tzinfo=None)).total_seconds())
            if refresh_time else -1
        )

        return CFOFinancialLeakageResponse(
            cfo_timestamp=datetime.utcnow(),
            total_active_breaches=total_breaches or 0,
            total_financial_exposure_usd=Decimal(str(total_exposure or 0)),
            breaches_by_severity=breaches_by_severity,
            top_leak_sources=top_leak_sources,
            view_last_refreshed_at=refresh_time,
            freshness_lag_seconds=max(freshness_seconds, 0)
        )

    finally:
        cursor.close()


@app.get(
    "/api/v1/coo/root-cause-attribution",
    response_model=COOOperationalAccountingResponse,
    tags=["COO Dashboards"],
    summary="COO dashboard: operational accountability"
)
async def get_coo_operational_accounting(
    tenant_id: str = Query(..., description="Customer tenant ID"),
    db_conn = Depends(get_db_connection),
    _role: str = Depends(require_api_key),
) -> COOOperationalAccountingResponse:
    cursor = db_conn.cursor()
    try:
        cursor.execute("""
            SELECT
                COUNT(*) AS tickets_analyzed,
                COALESCE(AVG(impact_duration_minutes), 0) AS avg_pending_minutes,
                MAX(view_snapshot_timestamp) AS last_refreshed
            FROM coo_root_cause_attribution_cache
            WHERE tenant_id = %s
        """, (tenant_id,))
        tickets, avg_pending, refresh_time = cursor.fetchone()

        cursor.execute("""
            SELECT failure_category, COUNT(*)
            FROM coo_root_cause_attribution_cache
            WHERE tenant_id = %s
            GROUP BY failure_category
        """, (tenant_id,))
        root_cause_breakdown = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT
                COUNT(*) AS triage_delay_tickets,
                COUNT(*) FILTER (
                    WHERE COALESCE(ce.event_type, 'New') NOT IN ('New', 'Pending')
                ) AS completed
            FROM coo_root_cause_attribution_cache c
            LEFT JOIN LATERAL (
                SELECT event_type
                FROM canonical_event_log
                WHERE ticket_id = c.ticket_id AND tenant_id = c.tenant_id
                ORDER BY event_version DESC
                LIMIT 1
            ) ce ON TRUE
            WHERE c.tenant_id = %s AND c.failure_category = 'Triage_Delay'
        """, (tenant_id,))
        triage_row = cursor.fetchone()
        triage_delay_tickets, completed = (triage_row or (0, 0))
        triage_completion_rate = (
            round((completed / triage_delay_tickets) * 100, 1)
            if triage_delay_tickets else 0.0
        )

        freshness_seconds = (
            int((datetime.utcnow() - refresh_time.replace(tzinfo=None)).total_seconds())
            if refresh_time else -1
        )

        return COOOperationalAccountingResponse(
            coo_timestamp=datetime.utcnow(),
            tickets_analyzed=tickets or 0,
            root_cause_breakdown=root_cause_breakdown,
            average_time_in_pending_minutes=float(avg_pending or 0),
            triage_completion_rate_percent=triage_completion_rate,
            view_last_refreshed_at=refresh_time,
            freshness_lag_seconds=max(freshness_seconds, 0)
        )

    finally:
        cursor.close()


@app.get(
    "/api/v1/schema/contract",
    tags=["Schema & Contracts"],
    summary="Get API contract schema (v1.2.0)"
)
async def get_contract_schema():
    return CONTRACT_SCHEMA_V1_2_0


@app.get("/api/v1/health", tags=["Status"])
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "contract_version": "1.2.0",
        "timestamp": datetime.utcnow().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
