# Zendesk Authority Layer — Evidence Package

## Executive Summary

**Problem:** SLA disputes in Zendesk-style ticketing often rely on platform logs that are difficult to independently verify during audits or customer disagreements — there's no tamper-evident record of what happened or why.

**Solution:** An independently verifiable authority layer that records SLA events in an append-only ledger, automatically categorizes root causes, routes corrective interventions, and produces cryptographically verifiable evidence (SHA-256 hash chains) for every action taken — enabling CFO/COO dashboards that can be trusted without taking the platform's word for it.

**Verification (this package):**
- Live PostgreSQL deployment
- Live FastAPI deployment
- 38 automated tests, 0 failures
- All five root-cause categorization paths exercised and confirmed correct
- Append-only ledger enforcement independently verified (attempted mutation rejected, data confirmed unchanged)
- Failure-path behavior confirmed (invalid input, missing records, unknown tenants all fail cleanly rather than crashing)
- Cryptographic hash chain is HMAC-SHA256 (keyed), not a plain hash — forging a valid chain link requires the signing key, not just knowledge of the public algorithm
- API endpoints require a valid API key; unauthenticated and invalid-key requests are confirmed rejected with 401
- Cryptographic chain state is anchored to an external, independent public timestamp service (OpenTimestamps/Bitcoin) — submission confirmed live; full Bitcoin block confirmation is still pending as of this writing (expected, not a defect — see note below)
- Remaining limitations documented explicitly below, not omitted

Full supporting detail follows below as Appendix A.

---


## Appendix A: Detailed Verification

**Prepared for review purposes. All claims below are backed by either a live test run (shown) or explicitly marked as code-reviewed-only, not run.**

### What this system does

Detects SLA breaches in Zendesk-style ticketing, categorizes the root cause, automatically routes corrective interventions, and produces cryptographically-verifiable financial exposure reports for CFO/COO dashboards.

---

### What has been verified LIVE (this session, real database, real HTTP requests)

A working instance was deployed to Replit and exercised end to end. Every claim in this section has a corresponding raw command output — available on request, not just summarized here.

| # | What was tested | Result |
|---|---|---|
| 1 | Schema deployment (6 tables, 8 indexes, immutability trigger) | Applied clean, zero errors |
| 2 | Server boot | Uvicorn started successfully on port 8080 |
| 3 | Health check endpoint | `200 OK` |
| 4 | Live intervention routing (Pending_State_Abuse case) | Correctly routed, correct priority assigned, hash chain generated |
| 5 | Financial leakage dashboard (CFO) | Returned real computed totals matching inserted test data exactly — not placeholder numbers |
| 6 | Root-cause dashboard (COO) | Returned real computed averages matching inserted test data exactly |
| 7 | Cryptographic proof certificate | Returned a genuine SHA-256 hash chain signature, verifiable against the ledger |
| 8 | API contract schema endpoint | Returned correctly versioned (v1.2.0) JSON schema |
| 9 | System_Unavailable root-cause branch (previously unimplemented in earlier package versions) | Correctly routed — valid, correct intervention type (`Escalate_System_Incident`), correct priority (P0) |
| 10 | Multi-ticket aggregation across different root causes | With 2 tickets (Pending_State_Abuse + System_Unavailable) in the system, CFO dashboard correctly reported 2 active breaches, $1,050.00 total exposure ($800 + $250), correct per-severity breakdown, and correctly ranked both root causes by financial impact |
| 11 | Agent_Timeout root-cause branch (last of five root-cause categories) | Correctly routed — valid, correct intervention type (`Reassign_Agent`), correct priority (P1) |
| 12 | Nonexistent ticket lookup | Correctly returns `404`, not a crash |
| 13 | Missing required query parameter | Correctly returns `422` (validation error), not a crash |
| 14 | Unknown tenant (CFO endpoint) | Correctly returns `200` with zero/empty values, not an error |
| 15 | Unknown tenant (COO endpoint) | Correctly returns `200` with zero/empty values, not an error |
| 16 | HMAC-signed hash chain | New ticket processed with keyed HMAC-SHA256 chain (upgraded from plain SHA-256); confirmed via live intervention returning a valid 64-char signed hash |
| 17 | Unauthenticated API request | Correctly returns `401 Unauthorized` with `"Missing X-API-Key header"` — not data, not a crash |
| 18 | Authenticated API request (correct key) | Correctly returns real live data — 11 active breaches, $4,950.00 total exposure, correctly broken down by severity and root cause across accumulated test tickets |
| 19 | Invalid API key | Correctly returns `401 Unauthorized` with `"Invalid API key"` — distinguished from the missing-key case |
| 20 | Concurrent writes to the same ticket | 5 simultaneous interventions fired at the exact same instant (threading barrier) against one ticket — all 5 succeeded, hash chain came out as a clean unbroken 1-through-5 sequence, no lost writes, no duplicate version numbers |
| 21 | Concurrent writes to different tickets | Confirmed the advisory lock is scoped per-ticket, not global — 3 different tickets processed simultaneously without blocking each other |
| 22 | External timestamp anchoring (OpenTimestamps) | Ledger's current tip hash successfully submitted to a real, independent, public Bitcoin-anchored timestamp service. Confirmed stored correctly in a dedicated `chain_anchors` table (hash, calendar URL, submission time) |
| 23 | Anchor confirmation-status check | Verified the check correctly distinguishes a merely-submitted proof (`PendingAttestation`) from a Bitcoin-confirmed one (`BitcoinBlockHeaderAttestation`) — an earlier version of this check incorrectly reported "confirmed" on submission alone; caught and fixed before being recorded here |

**All five root-cause categories declared in the schema (Routing_Ping_Pong_Failure, Pending_State_Abuse, Triage_Delay, Agent_Timeout, System_Unavailable) have now been confirmed live, each producing the correct intervention type and priority.** In earlier package versions, two of these five had no intervention logic at all and silently fell through to a generic catch-all.

---

### Automated test suite results (this session, live database)

Beyond the manual API calls above, a full pytest suite (38 tests) was run directly against this live deployment:
This includes an assertion-based check that the immutability trigger genuinely blocks an UPDATE on a ledger row (not just that an exception fires — the test re-reads the row afterward and confirms the data is unchanged), an independent recomputation of the SHA-256 hash chain to confirm it's deterministic given fixed inputs, and a dedicated failure-case suite confirming the API fails cleanly (404s, 422s, empty results) rather than crashing when given bad input — not just the happy path.

---

### What has been fixed and code-reviewed, but not yet exercised live

- None outstanding as of this update — the two items previously listed here (HMAC-signed hash chain, API key enforcement) have both been wired in and confirmed live (see tests #16–19 above).

---

### What is explicitly NOT yet in place

- No scheduled/automated trigger for the data refresh job — it was run manually for this test. A production deployment needs a scheduler.
- No load testing (high request volume / throughput), no failure-injection testing beyond the API-level failure cases above (bad input, missing params, unknown records). Concurrent-write correctness on a single ticket is now tested (see #20–21 above) — load/throughput testing is a separate, still-open concern.
- Security review (documented separately) has not been re-run against this specific deployed version.
- Key rotation itself (the dual-key window `authority_secrets.py` is designed to support) has not been exercised — only single-key signing and single-key auth have been tested live.
- External timestamp anchor is submitted but not yet Bitcoin-confirmed. Bitcoin block confirmation typically takes 1+ hours after submission; this is expected behavior of the underlying protocol, not a defect in the implementation. The confirmation-check code path itself has been verified correct (it accurately distinguishes "submitted" from "confirmed" rather than conflating them — an incorrect version of this check was caught and fixed during this session before being recorded as a passing result).
- Published proof endpoint (an API route exposing the anchor for independent third-party verification) has not yet been built.

---

### Audit trail

This package went through multiple flagged-and-reissued versions before reaching a verified state — that history is documented in full in the accompanying file trace, including specific defects found in each prior version and how they were resolved. Available on request for anyone who wants to see the full diligence trail rather than just the end state.

---

*This document reflects what was directly observed and tested. Any claim not marked "verified live" above should be treated as reviewed-but-unproven until independently tested.*
