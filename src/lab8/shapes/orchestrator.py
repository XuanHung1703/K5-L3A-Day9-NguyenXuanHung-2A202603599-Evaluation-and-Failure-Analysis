"""Shape C — orchestrator plus read-only investigators. Student work.

1. Build a handoff with `lab8.handoff.make_handoff`. Allowed tools are read-only.
   Never put parent_secret, raw headers, or the full claim row into facts.
2. `lab8.runtime.run_readonly_investigators` runs those tools.
3. The orchestrator quotes from the investigator's order view and calls
   `durability.issue_refund`. Investigators have no write registry.
   Pass the full quote; the host subtracts earlier refunds on the same order.
   `lookup_refund_history` is a read-only tool you may hand to an investigator.
4. Trace the sanitized handoff, not the parent context.

An LLM summary of the parent context is not a sanitizer. Use the allowlist.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from __future__ import annotations

from lab8.db import connect
from lab8.durability import issue_refund
from lab8.handoff import make_handoff
from lab8.runtime import run_readonly_investigators
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.tools import compute_compensation, get_claim_view, tool_cost
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
        budget = Budget()
        run_id = make_run_id("orchestrator", claim_id, seed)
        trace = Trace(run_id)

        def stop(
            status: str,
            reason: str,
            proposal_amount: int = 0,
        ) -> RunResult:
            trace.add("decision", {
                "status": status,
                "reason": reason,
                "proposal_amount": proposal_amount,
            })

            return finish(
                conn,
                shape="orchestrator",
                claim_id=claim_id,
                seed=seed,
                status=status,
                proposal_amount=proposal_amount,
                budget=budget,
                trace=trace,
                error_reason=None if status == "resolved" else reason,
            )

        # 1. Đọc claim; không ghi nguyên claim hoặc ticket vào trace.
        budget.add_tool(tool_cost())
        claim = get_claim_view(conn, claim_id)

        if not claim["found"]:
            return stop("failed", "unknown_claim")

        if not claim.get("order_id"):
            return stop("needs_info", "missing_order_id")

        # 2. Tạo handoff, chỉ cấp quyền tra cứu.
        handoff = make_handoff(
            request_id=f"REQ-{claim_id}",
            claim_id=claim_id,
            task="check_applicable_policy",
            facts={},
            allowed_tools=["lookup_order", "lookup_policy"],
        )
        trace.add("handoff", handoff)

        # 3. Investigator tra cứu trong phạm vi người gửi claim.
        investigated = run_readonly_investigators(
            conn,
            budget,
            handoff,
            principal_id=claim["principal_id"],
        )

        order_view = investigated["tools"].get("lookup_order", {})
        trace.add("investigator", {
            "order_visible": bool(order_view.get("visible")),
        })

        if not order_view.get("visible"):
            return stop(
                "escalated",
                order_view.get("reason", "order_not_visible"),
            )

        # 4. Code tính tiền từ dữ liệu đơn và policy hiện hành.
        budget.add_tool(tool_cost())
        quote = compute_compensation(conn, order_view["order"])
        proposal = int(quote["amount_vnd"])
        trace.add("quote", quote)

        if proposal <= 0:
            return stop(
                "denied",
                quote.get("reason", "not_eligible"),
            )

        # 5. Host kiểm approval, trần theo đơn và chống ghi trùng.
        # Truyền quote đầy đủ, không tự trừ tiền đã hoàn.
        # Không bắt InjectedCrash để test crash/resume hoạt động.
        outcome = issue_refund(
            conn,
            claim_id,
            proposal,
            crash_at=crash_at,
        )

        trace.add("host_result", {
            "ok": outcome["ok"],
            "reason": outcome["reason"],
        })

        if not outcome["ok"]:
            status = "failed" if outcome["conflict"] else "denied"
            return stop(status, outcome["reason"], proposal)

        return stop("resolved", outcome["reason"], proposal)

    finally:
        conn.close()