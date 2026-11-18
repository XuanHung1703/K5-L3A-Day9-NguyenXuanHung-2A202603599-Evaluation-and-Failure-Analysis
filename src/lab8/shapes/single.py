"""Shape B — one ReAct agent. Student work.

Use `lab8.runtime.run_react` with max_steps=8. `decide` may pick a read tool.
It must not call `issue_refund`. After the loop, the host validates the quote
and is the only writer.

A decide() that trusts ticket text over the order row will fail hidden claims
where the customer overstates the delay or cites a superseded clause.

Per-order cap: an order may already have been refunded by an earlier claim.
The read tool `lookup_refund_history` shows how much. The host still enforces
the cap, so pass the full quote to `durability.issue_refund`, not a net amount.

Caps: stop at 8 steps. Count model calls in the Budget so cost stays comparable.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.mock_llm import complete
from lab8.runtime import run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(conn, claim_id: str, *, seed: int, crash_at: str | None) -> RunResult:
    """Run one claim through a bounded, read-only ReAct agent."""
    budget = Budget()
    trace = Trace(make_run_id("single", claim_id, seed))

    # Read through the allowlisted view. Never put the raw claims row in the
    # observation or trace because it also contains secrets and raw headers.
    budget.add_tool(tool_cost())
    claim = get_claim_view(conn, claim_id)
    if not claim.get("found"):
        trace.add("error", {"reason": "unknown_claim"})
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status="failed",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="unknown_claim",
        )

    def decide(observation: dict) -> dict:
        """Choose the next read tool from the latest safe observation."""
        last_tool = observation.get("last_tool")
        last_result = observation.get("last_result") or {}

        # MockLLM stands in for the model. Its prose is intentionally not used
        # for money or authorization decisions, but the call must be budgeted.
        complete(
            budget,
            seed=seed,
            purpose="decide",
            prompt=f"claim={claim_id};last_tool={last_tool or 'start'}",
        )

        if last_tool is None:
            if not claim.get("order_id"):
                return {
                    "final": {
                        "status": "needs_info",
                        "error_reason": "missing_order_id",
                    }
                }
            return {
                "tool": "lookup_order",
                "args": {
                    "order_id": claim["order_id"],
                    "principal_id": claim["principal_id"],
                },
            }

        if last_tool == "lookup_order":
            if not last_result.get("visible"):
                return {
                    "final": {
                        "status": "escalated",
                        "error_reason": last_result.get("reason", "order_not_visible"),
                    }
                }
            # Structured order data is the source of truth. In particular, do
            # not copy delay or damage claims from the customer's ticket.
            return {
                "tool": "compute_compensation",
                "args": {"order": last_result["order"]},
            }

        if last_tool == "compute_compensation":
            return {"final": {"status": "quoted", "quote": last_result}}

        return {
            "final": {
                "status": "failed",
                "error_reason": "unexpected_agent_state",
            }
        }

    agent_result = run_react(
        conn,
        budget,
        observation={"claim": claim},
        decide=decide,
        max_steps=8,
        worker=True,
    )
    final = agent_result["final"]
    trace.add(
        "agent_stop",
        {
            "stopped": agent_result["stopped"],
            "status": final.get("status", "failed"),
        },
    )

    final_status = final.get("status")
    if final_status != "quoted":
        status = final_status if final_status in {"needs_info", "escalated", "failed"} else "failed"
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=final.get("error_reason", "agent_failed"),
        )

    quote_payload = final["quote"]
    proposal = int(quote_payload["amount_vnd"])
    trace.add("quote", quote_payload)
    if proposal <= 0:
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status="denied",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=quote_payload.get("reason"),
        )

    # The host owns approval, the per-order cap, idempotency, and the write.
    # Pass the full quote; the host subtracts earlier refunds when necessary.
    try:
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise

    trace.add("refund_gate", {"ok": outcome["ok"], "reason": outcome["reason"]})
    if not outcome["ok"]:
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status="failed" if outcome["conflict"] else "denied",
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=outcome["reason"],
        )

    return finish(
        conn,
        shape="single",
        claim_id=claim_id,
        seed=seed,
        status="resolved",
        proposal_amount=proposal,
        budget=budget,
        trace=trace,
        error_reason=None,
    )
