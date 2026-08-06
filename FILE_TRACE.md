# Zendesk Authority Layer — File Trace
**Role held throughout:** Outside auditor / trace-holder. No goggles adopted, no passes generated directly — findings logged, fixes verified, live tests run and recorded.

**Status as of this trace: LIVE AND VERIFIED.** Full pipeline (schema → intervention router → refresh strategy → API layer) is running on Replit (`samtuck54/FreeIndustri...`) and has returned correct, real (non-stub) data from all four API endpoints against live test data.

---

## Package version history

| Package | Result |
|---|---|
| `zendesk-authority-layer-CORRECTED-1.zip` | 16 bugs flagged (schema, router, API layer, refresh strategy, tests, docs) |
| `zendesk-authority-layer-CORRECTED-2.zip` | Byte-for-byte identical to v1 — no fixes applied |
| `zendesk-authority-layer-CORRECTED.zip` (3rd upload) | Byte-for-byte identical to v1 — no fixes applied |
| `zendesk-authority-complete-v2.zip` | New file structure, 7 secondary bugs claimed fixed. Verified: 1 of 7 actually fixed (timestamp comparison). Remaining 6 either unresolved or replaced with new variants (phantom columns referencing tables/columns that don't exist, orphaned staging table never created, zero-assertion tests, broken conftest.py import path) |
| **This session — full fix pass ("v3 audit pass")** | All 16 original items + all 7 v2 secondary items addressed via architectural fix (materialized views → real indexed cache tables), then manually deployed and live-tested |

---

## Root cause identified this session

Every prior refresh-strategy bug (materialized view incompatibility, incomplete upsert, dead partition-detection code, wrong freshness signal) traced back to one design contradiction: trying to get writable, incrementally-upsertable behavior out of a Postgres `MATERIALIZED VIEW`, which Postgres does not support. Fix: converted `mv_cfo_financial_leakage` / `mv_coo_root_cause_attribution` into real tables (`cfo_financial_leakage_cache`, `coo_root_cause_attribution_cache`) with proper primary keys, populated by upsert instead of view refresh.

---

## Files fixed and deployed (all four confirmed byte-complete via structural diff before upload)

| File | Key fixes |
|---|---|
| `artifact_13_append_only_ledger_FIXED.sql` | Real immutability trigger (replaces non-functional CHECK constraint); added cache tables; consistent field naming |
| `artifact_18_live_interception_router_FIXED.py` | Fixed priority/status field mix-up (Pending_State_Abuse now assigns P2, not a copy of ticket status); `sla_breach_seconds` now actually used; added missing Agent_Timeout and System_Unavailable branches; fixed cursor leak in `execute_live_intervention` |
| `artifact_19_api_layer_FIXED.py` (deployed as `artifact_19_api_layer_CORRECTED.py`) | Reads from real cache tables, not materialized views; renamed misleading `sla_contract_limit_minutes` → `elapsed_breach_minutes`; `breaches_by_severity`/`top_leak_sources`/`root_cause_breakdown`/`triage_completion_rate_percent` computed from real queries, not hardcoded stubs; freshness reads real `view_snapshot_timestamp`, not `pg_stat_get_last_vacuum_time()`; wired to real `Depends(get_db_connection)` instead of dead `db_conn=None` |
| `artifact_19_refresh_strategy_FIXED.py` | Populates real cache tables via correct joins (event_lineage_chain for hash, sla_root_cause_attribution for financials); filters on real `attribution_timestamp`, not epoch-vs-sequence-index mismatch; full upsert updates every field on conflict |

**Supporting infrastructure added this session (new files, not audited from prior packages):**
- `database.py` — FastAPI dependency yielding a psycopg2 connection from `DATABASE_URL`
- `main.py` — entry point, boots the FastAPI app via uvicorn
- Two Replit Secrets set: `ZENDESK_AUTHORITY_SIGNING_KEY`, `ZENDESK_AUTHORITY_API_KEY`

---

## Live verification (this session, Replit shell)

1. Schema applied clean — 6 tables, 8 indexes, 1 trigger, 0 errors
2. Dependencies installed (`fastapi`, `uvicorn`, `psycopg2-binary`, `pydantic`) — clean
3. Server booted — `Uvicorn running on http://0.0.0.0:8080`
4. Test ticket `TEST-001` (Pending_State_Abuse) inserted → intervention correctly returned `valid=True`, `intervention_type=Restore_Open_State`
5. Refresh job ran clean against real data
6. **`GET /api/v1/health`** → `200 OK`, correct payload
7. **`GET /api/v1/cfo/financial-leakage`** → real computed values: 1 active breach, $250.00 exposure, `breaches_by_severity: {"P2": 1}` (confirms the priority fix — was previously hardcoded `{"P0": 12, "P1": 28, "P2": 7}` regardless of data)
8. **`GET /api/v1/coo/root-cause-attribution`** → real computed values: `average_time_in_pending_minutes: 90.0` (exact match to inserted data), `triage_completion_rate_percent: 0.0` (correct — no Triage_Delay tickets exist yet, handled without divide-by-zero)
9. **`GET /api/v1/financial-certificate/TEST-001`** → real hash signature, `elapsed_breach_minutes: 90` (renamed field, correct value)
10. **`GET /api/v1/schema/contract`** → v1.2.0 contract returned correctly

**All four API endpoints confirmed returning correct, real, non-stub data end to end.**

---

## Open items / not yet tested

- TEST-002 (System_Unavailable branch, exercises previously-missing intervention logic) was queued but not confirmed completed in this session — worth a follow-up run to confirm Agent_Timeout / System_Unavailable branches behave correctly live, not just via code review.
- `authority_secrets.py` (the KMS-rotation-ready secrets module reviewed earlier) is in the project and IS wired into `auth.py` (`get_api_key_role_map()`) and `artifact_18_live_interception_router_FIXED.py` (`get_signing_key()`).
- Pydantic deprecation warning (`schema_extra` → `json_schema_extra`) — fixed this session in `artifact_19_api_layer_CORRECTED.py`.
- Monthly archive/compression job added this session (`monthly_archive_job.py` + `artifact_20_ledger_archive_schema.sql`) — needs a Replit Scheduled Deployment pointed at it for the 5th-of-month cron to actually fire.
- Test suite (`test_integration_zeromock.py`, rewritten this session with real assertions) was not run against the live Replit database — only manually equivalent checks (direct curl/psql calls) were performed.
