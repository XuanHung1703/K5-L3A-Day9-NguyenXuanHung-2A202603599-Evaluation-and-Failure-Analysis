from lab8.db import init_store
from lab8.shapes.single import run_claim
from tests.conftest import CLAIMS, WORLD


def test_single_agent_trusts_order_over_ticket(tmp_path):
    store = tmp_path / "single.sqlite"
    init_store(store, WORLD, CLAIMS).close()

    result = run_claim(
        "C-002",
        seed=55,
        store_path=str(store),
    )

    assert result.status == "denied"
    assert result.proposal_amount == 0
    assert result.refund_effects == []