import pytest

from lab8.handoff import HandoffError, make_handoff


def test_handoff_rejects_refund_tool():
    # Arrange: chuẩn bị gói giao việc có tool ghi tiền.
    allowed_tools = ["lookup_order", "issue_refund"]

    # Act + Assert: tạo handoff phải bị từ chối.
    with pytest.raises(HandoffError):
        make_handoff(
            request_id="REQ-TEST",
            claim_id="C-TEST",
            task="check_applicable_policy",
            facts={},
            allowed_tools=allowed_tools,
        )
def test_handoff_accepts_readonly_tools():
    # Tool chỉ đọc phải được chấp nhận.
    allowed_tools = ["lookup_order", "lookup_policy"]

    handoff = make_handoff(
        request_id="REQ-TEST",
        claim_id="C-TEST",
        task="check_applicable_policy",
        facts={},
        allowed_tools=allowed_tools,
    )

    assert handoff["allowed_tools"] == allowed_tools
    assert handoff["principal_scope"] == "owner_order_only"


def test_handoff_filters_sensitive_facts():
    # Dữ kiện hợp lệ được giữ; field nhạy cảm bị loại.
    handoff = make_handoff(
        request_id="REQ-TEST",
        claim_id="C-TEST",
        task="check_applicable_policy",
        facts={
            "delay_days": 4,
            "parent_secret": "CANARY_SECRET_TEST",
            "raw_headers": {"Authorization": "test-token"},
            "phone": "0900000000",
        },
        allowed_tools=["lookup_order"],
    )

    assert handoff["facts"] == {"delay_days": 4}


def test_handoff_rejects_secret_in_task():
    # Secret còn nằm trong nội dung được chuyển đi phải bị chặn.
    with pytest.raises(HandoffError):
        make_handoff(
            request_id="REQ-TEST",
            claim_id="C-TEST",
            task="Check CANARY_SECRET_TEST",
            facts={},
            allowed_tools=["lookup_order"],
        )