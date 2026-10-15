import pytest

from stock_repost.gl import gl_entries
from stock_repost.scenario import EDITED_RECEIPT, NEW_RATE, build_ledger

OPENING = "MAT-STE-2026-00001"
DN_MILK = "MAT-DN-2026-00001"
PR_20TH = "MAT-PRE-2026-00002"
MANUFACTURE = "MAT-STE-2026-00002"
DN_POWDER = "MAT-DN-2026-00002"

# voucher, item, stock_value_difference, qty_after_transaction, stock_value, stock_queue
BEFORE = [
    (OPENING, "Milk", 5000, 100, 5000, [[100, 50]]),
    (EDITED_RECEIPT, "Milk", 3000, 150, 8000, [[100, 50], [50, 60]]),
    (DN_MILK, "Milk", -4000, 70, 4000, [[20, 50], [50, 60]]),
    (PR_20TH, "Milk", 3000, 120, 7000, [[20, 50], [100, 60]]),
    (MANUFACTURE, "Milk", -5800, 20, 1200, [[20, 60]]),
    (MANUFACTURE, "Milk Powder", 5800, 10, 5800, [[10, 580]]),
    (DN_POWDER, "Milk Powder", -5800, 0, 0, []),
]

AFTER = [
    (OPENING, "Milk", 5000, 100, 5000, [[100, 50]]),
    (EDITED_RECEIPT, "Milk", 4000, 150, 9000, [[100, 50], [50, 80]]),
    (DN_MILK, "Milk", -4000, 70, 5000, [[20, 50], [50, 80]]),
    (PR_20TH, "Milk", 3000, 120, 8000, [[20, 50], [50, 80], [50, 60]]),
    (MANUFACTURE, "Milk", -6800, 20, 1200, [[20, 60]]),
    (MANUFACTURE, "Milk Powder", 6800, 10, 6800, [[10, 680]]),
    (DN_POWDER, "Milk Powder", -6800, 0, 0, []),
]


def entry(ledger, voucher_no, item_code):
    return next(sle for sle in ledger.voucher_entries(voucher_no) if sle.item_code == item_code)


def balance(sle):
    return (sle.stock_value_difference, sle.qty_after_transaction, sle.stock_value, sle.stock_queue)


@pytest.fixture
def ledger():
    return build_ledger()


@pytest.fixture
def reposted():
    ledger = build_ledger()
    result = ledger.adjust_incoming_rate(EDITED_RECEIPT, NEW_RATE)
    return ledger, result


@pytest.mark.parametrize("voucher_no, item_code, svd, qty, value, queue", BEFORE)
def test_ledger_before_the_rate_change(ledger, voucher_no, item_code, svd, qty, value, queue):
    assert balance(entry(ledger, voucher_no, item_code)) == (svd, qty, value, queue)


@pytest.mark.parametrize("voucher_no, item_code, svd, qty, value, queue", AFTER)
def test_ledger_after_the_rate_change(reposted, voucher_no, item_code, svd, qty, value, queue):
    ledger, _ = reposted
    assert balance(entry(ledger, voucher_no, item_code)) == (svd, qty, value, queue)


def test_receipt_keeps_its_document_rate(reposted):
    ledger, _ = reposted
    receipt = ledger.vouchers[EDITED_RECEIPT]
    assert (receipt.rate, receipt.valuation_rate) == (60, 80)
    assert entry(ledger, EDITED_RECEIPT, "Milk").incoming_rate == 80


def test_delivery_on_the_15th_keeps_its_cost_but_its_balance_moves(ledger):
    dn = entry(ledger, DN_MILK, "Milk")
    assert (dn.stock_value_difference, dn.stock_value) == (-4000, 4000)

    result = ledger.adjust_incoming_rate(EDITED_RECEIPT, NEW_RATE)

    # FIFO took all 80 L from the opening 100 L @ 50, so the 10 Jan layer never reached this delivery
    assert (dn.stock_value_difference, dn.stock_value) == (-4000, 5000)
    assert ledger.vouchers[DN_MILK].incoming_rate == 50
    assert dn.name in result.changed
    assert DN_MILK not in result.affected_vouchers


def test_milk_powder_is_revalued_from_the_milk_it_consumed(reposted):
    ledger, _ = reposted
    stock_entry = ledger.vouchers[MANUFACTURE]
    milk_row, powder_row = stock_entry.raw_material_rows[0], stock_entry.finished_item_row

    assert (milk_row.basic_amount, milk_row.basic_rate) == (6800, 68)
    assert (powder_row.basic_amount, powder_row.basic_rate) == (6800, 680)
    assert ledger.vouchers[DN_POWDER].incoming_rate == 680


def test_milk_closing_balance_is_the_same_before_and_after(ledger):
    closing_before = ledger.entries_for("Milk", "Stores")[-1]
    assert (closing_before.qty_after_transaction, closing_before.stock_value) == (20, 1200)

    ledger.adjust_incoming_rate(EDITED_RECEIPT, NEW_RATE)

    closing_after = ledger.entries_for("Milk", "Stores")[-1]
    assert (closing_after.qty_after_transaction, closing_after.stock_value) == (20, 1200)


def test_repost_starts_at_the_edited_receipt(reposted):
    ledger, result = reposted
    in_order = sorted(ledger.entries.values(), key=lambda sle: sle.sort_key)

    assert result.processed == [sle.name for sle in in_order[1:]]
    assert entry(ledger, OPENING, "Milk").name not in result.processed
    assert result.affected_vouchers == [EDITED_RECEIPT, MANUFACTURE, DN_POWDER]


def test_gl_entries_before_and_after(ledger):
    before = {voucher_no: gl_entries(ledger, voucher_no) for voucher_no in ledger.vouchers}
    ledger.adjust_incoming_rate(EDITED_RECEIPT, NEW_RATE)
    after = {voucher_no: gl_entries(ledger, voucher_no) for voucher_no in ledger.vouchers}

    assert before[EDITED_RECEIPT] == {"Stock In Hand": 3000, "Stock Received But Not Billed": -3000}
    assert after[EDITED_RECEIPT] == {"Stock In Hand": 4000, "Stock Received But Not Billed": -4000}
    assert before[DN_POWDER] == {"Cost of Goods Sold": 5800, "Stock In Hand": -5800}
    assert after[DN_POWDER] == {"Cost of Goods Sold": 6800, "Stock In Hand": -6800}

    for unchanged in (OPENING, DN_MILK, PR_20TH, MANUFACTURE):
        assert before[unchanged] == after[unchanged]
    # Milk out and Milk Powder in hit the same Stock In Hand account and cancel out
    assert after[MANUFACTURE] == {}


def test_every_voucher_balances(reposted):
    ledger, _ = reposted
    for voucher_no in ledger.vouchers:
        assert sum(gl_entries(ledger, voucher_no).values()) == 0
