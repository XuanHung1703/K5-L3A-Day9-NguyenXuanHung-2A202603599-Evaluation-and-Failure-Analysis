import json

from lab8.db import connect
from lab8.durability import get_refund
from lab8.shapes.workflow import run_claim


def test_unknown_claim_fails_without_refund_and_writes_trace(public_db):
    claim_id = "C-DOES-NOT-EXIST"

    result = run_claim(
        claim_id,
        seed=11,
        store_path=str(public_db),
    )

    assert result.status == "failed"
    assert result.claim_id == claim_id
    assert result.proposal_amount == 0
    assert result.error_reason == "unknown_claim"

    conn = connect(public_db)
    try:
        assert get_refund(conn, claim_id) is None
    finally:
        conn.close()

    with open(result.trace_path, encoding="utf-8") as trace_file:
        trace = json.load(trace_file)

    assert trace["run_id"] == result.run_id
    assert isinstance(trace["events"], list)