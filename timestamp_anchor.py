"""
External timestamp anchoring via OpenTimestamps.

Anchors the current tip hash of a tenant's ledger chain to the Bitcoin
blockchain via OpenTimestamps' free public calendar servers. This upgrades
the tamper-evidence guarantee from "detectable within our own database" to
"detectable against a public record nobody -- including us -- controls.

IMPORTANT: submission is NOT confirmation. submit_anchor() gets you a
PENDING proof immediately. The proof only becomes fully verifiable once the
submitted hash is actually included in a Bitcoin block, which typically
takes 1+ hours. check_anchor_status() can be re-run later to see if a
pending anchor has since confirmed.
"""

import psycopg2
from opentimestamps.calendar import RemoteCalendar
from opentimestamps.core.serialize import BytesSerializationContext, BytesDeserializationContext
from opentimestamps.core.timestamp import Timestamp


CALENDAR_URLS = [
    "https://alice.btc.calendar.opentimestamps.org",
    "https://bob.btc.calendar.opentimestamps.org",
    "https://finney.calendar.eternitywall.com",
]


def submit_anchor(tenant_id: str, db_conn) -> dict:
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT current_hash FROM canonical_event_log
        WHERE tenant_id = %s
        ORDER BY timestamp DESC
        LIMIT 1
    """, (tenant_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        return {"success": False, "error": f"No ledger entries found for tenant {tenant_id}"}

    tip_hash_hex = row[0]
    digest = bytes.fromhex(tip_hash_hex)

    last_error = None
    for calendar_url in CALENDAR_URLS:
        try:
            calendar = RemoteCalendar(calendar_url)
            proof_timestamp = calendar.submit(digest, timeout=15)

            ctx = BytesSerializationContext()
            proof_timestamp.serialize(ctx)
            proof_bytes = ctx.getbytes()

            cursor.execute("""
                INSERT INTO chain_anchors (tenant_id, anchored_hash, ots_proof_bytes, calendar_url)
                VALUES (%s, %s, %s, %s)
            """, (tenant_id, tip_hash_hex, psycopg2.Binary(proof_bytes), calendar_url))
            db_conn.commit()
            cursor.close()

            return {
                "success": True,
                "anchored_hash": tip_hash_hex,
                "calendar_url": calendar_url,
            }

        except Exception as e:
            last_error = str(e)
            continue

    cursor.close()
    return {"success": False, "error": f"All calendar servers failed. Last error: {last_error}"}


def check_anchor_status(tenant_id: str, db_conn) -> list:
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT anchor_id, anchored_hash, ots_proof_bytes, calendar_url, submitted_at, confirmed_at
        FROM chain_anchors
        WHERE tenant_id = %s
        ORDER BY submitted_at DESC
    """, (tenant_id,))
    rows = cursor.fetchall()

    results = []
    for anchor_id, anchored_hash, proof_bytes, calendar_url, submitted_at, confirmed_at in rows:
        if confirmed_at is not None:
            results.append({
                "anchored_hash": anchored_hash,
                "confirmed": True,
                "calendar_url": calendar_url,
                "submitted_at": submitted_at,
            })
            continue

        try:
            digest = bytes.fromhex(anchored_hash)
            ctx = BytesDeserializationContext(bytes(proof_bytes))
            proof_timestamp = Timestamp.deserialize(ctx, digest)

            is_confirmed = False
            for pair in proof_timestamp.all_attestations():
                attestation = pair[1]
                if type(attestation).__name__ == "BitcoinBlockHeaderAttestation":
                    is_confirmed = True

            if is_confirmed:
                cursor.execute("""
                    UPDATE chain_anchors SET confirmed_at = CURRENT_TIMESTAMP
                    WHERE anchor_id = %s
                """, (anchor_id,))
                db_conn.commit()

            results.append({
                "anchored_hash": anchored_hash,
                "confirmed": is_confirmed,
                "calendar_url": calendar_url,
                "submitted_at": submitted_at,
            })

        except Exception as e:
            results.append({
                "anchored_hash": anchored_hash,
                "confirmed": False,
                "calendar_url": calendar_url,
                "submitted_at": submitted_at,
                "check_error": str(e),
            })

    cursor.close()
    return results
