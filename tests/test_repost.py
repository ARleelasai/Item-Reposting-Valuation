import random
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest

from stock_repost import (
    DeliveryNote,
    Manufacture,
    MaterialReceipt,
    NegativeStockError,
    PurchaseReceipt,
    Receipt,
    StockLedger,
    gl_entries,
)
from stock_repost.scenario import EDITED_RECEIPT, NEW_RATE, WAREHOUSE, build_ledger, on


def balances(ledger):
    return {
        sle.name: (sle.qty_after_transaction, sle.stock_value, sle.stock_value_difference, sle.stock_queue)
        for sle in ledger.entries.values()
        if not sle.is_cancelled
    }


def only_entry(ledger, voucher_no):
    (sle,) = ledger.voucher_entries(voucher_no)
    return sle


def test_cancel_blocked_by_future_negative_stock():
    ledger = build_ledger()
    before = balances(ledger)

    # Without the 50 L from 10 Jan, the 21 Jan manufacture is 30 L short
    with pytest.raises(NegativeStockError, match="would be -30 on 21 Jan 2026"):
        ledger.cancel(EDITED_RECEIPT)

    assert balances(ledger) == before
    assert ledger.voucher_entries(EDITED_RECEIPT)


def test_backdated_receipt_revalues_a_later_delivery():
    ledger = StockLedger()
    ledger.submit(PurchaseReceipt("PR-1", on(2), "Milk", WAREHOUSE, 10, 50))
    ledger.submit(PurchaseReceipt("PR-2", on(4), "Milk", WAREHOUSE, 10, 70))
    ledger.submit(DeliveryNote("DN-1", on(6), "Milk", WAREHOUSE, 15))
    assert only_entry(ledger, "DN-1").stock_value_difference == -(10 * 50 + 5 * 70)

    ledger.submit(PurchaseReceipt("PR-0", on(1), "Milk", WAREHOUSE, 10, 40))

    assert only_entry(ledger, "DN-1").stock_value_difference == -(10 * 40 + 5 * 50)
    assert only_entry(ledger, "DN-1").stock_queue == [[5, 50], [10, 70]]


def test_entries_at_the_same_time_are_ordered_by_creation():
    ledger = StockLedger()
    ledger.submit(PurchaseReceipt("PR-1", on(1), "Milk", WAREHOUSE, 10, 50))
    ledger.submit(PurchaseReceipt("PR-2", on(2), "Milk", WAREHOUSE, 5, 60))
    ledger.submit(DeliveryNote("DN-1", on(3), "Milk", WAREHOUSE, 12))

    # Same posting time as PR-2 but created later, so it goes behind PR-2 in the queue
    ledger.submit(PurchaseReceipt("PR-3", on(2), "Milk", WAREHOUSE, 5, 40))

    assert only_entry(ledger, "PR-3").stock_queue == [[10, 50], [5, 60], [5, 40]]
    assert only_entry(ledger, "DN-1").stock_value_difference == -(10 * 50 + 2 * 60)


def test_repost_stops_when_the_queue_matches_again():
    ledger = build_ledger()
    ledger.submit(DeliveryNote("MAT-DN-2026-00003", on(28), "Milk", WAREHOUSE, 10))
    late_delivery = only_entry(ledger, "MAT-DN-2026-00003")

    result = ledger.adjust_incoming_rate(EDITED_RECEIPT, NEW_RATE)

    # Milk's queue is [[20, 60]] after 21 Jan either way, so 28 Jan is never looked at
    assert late_delivery.name not in result.processed
    assert late_delivery.stock_value_difference == -600

    replayed = build_ledger()
    replayed.submit(DeliveryNote("MAT-DN-2026-00003", on(28), "Milk", WAREHOUSE, 10))
    full = replayed.adjust_incoming_rate(EDITED_RECEIPT, NEW_RATE, full_replay=True)

    assert late_delivery.name in full.processed
    assert balances(replayed) == balances(ledger)


def test_same_rate_again_changes_nothing():
    ledger = build_ledger()
    ledger.adjust_incoming_rate(EDITED_RECEIPT, NEW_RATE)

    result = ledger.adjust_incoming_rate(EDITED_RECEIPT, NEW_RATE)

    assert result.processed == [only_entry(ledger, EDITED_RECEIPT).name]
    assert result.changed == []
    assert result.affected_vouchers == []


def test_backdated_delivery_that_empties_stock():
    ledger = StockLedger()
    ledger.submit(PurchaseReceipt("PR-1", on(1), "Milk", WAREHOUSE, 10, 50))
    ledger.submit(PurchaseReceipt("PR-2", on(5), "Milk", WAREHOUSE, 10, 60))
    ledger.submit(DeliveryNote("DN-2", on(6), "Milk", WAREHOUSE, 5))
    assert only_entry(ledger, "DN-2").stock_value_difference == -250

    # Leaves an empty queue on 2 Jan; the new entry has no stored queue to compare with, so the
    # walk must carry on instead of mistaking "empty" for "unchanged"
    ledger.submit(DeliveryNote("DN-1", on(2), "Milk", WAREHOUSE, 10))

    assert only_entry(ledger, "DN-1").stock_queue == []
    assert only_entry(ledger, "DN-2").stock_value_difference == -300


def test_manufacture_cannot_consume_its_own_output():
    with pytest.raises(ValueError):
        Manufacture("SE-1", on(1), WAREHOUSE, {"Milk": 10}, "Milk", 5)


def test_full_replay_repairs_a_corrupted_finished_good():
    ledger = build_ledger()
    powder = next(s for s in ledger.voucher_entries("MAT-STE-2026-00002") if s.item_code == "Milk Powder")
    powder.stock_queue = [[Decimal(10), Decimal(999)]]
    powder.stock_value_difference = Decimal(9990)

    ledger.adjust_incoming_rate(EDITED_RECEIPT, 60)
    assert powder.stock_queue == [[10, 999]]

    ledger.adjust_incoming_rate(EDITED_RECEIPT, 60, full_replay=True)
    assert powder.stock_queue == [[10, 580]]
    assert powder.stock_value_difference == 5800


def test_cancelling_a_voucher_lists_it_for_a_gl_repost():
    ledger = build_ledger()
    ledger.submit(DeliveryNote("MAT-DN-2026-00003", on(28), "Milk", WAREHOUSE, 10))

    result = ledger.cancel("MAT-DN-2026-00003")

    assert result.affected_vouchers == ["MAT-DN-2026-00003"]
    assert gl_entries(ledger, "MAT-DN-2026-00003") == {}


def test_cancel_and_adjust_refuse_unknown_and_cancelled_vouchers():
    ledger = build_ledger()
    ledger.submit(DeliveryNote("MAT-DN-2026-00003", on(28), "Milk", WAREHOUSE, 10))
    ledger.cancel("MAT-DN-2026-00003")

    with pytest.raises(KeyError):
        ledger.cancel("NOPE")
    with pytest.raises(ValueError, match="already cancelled"):
        ledger.cancel("MAT-DN-2026-00003")
    with pytest.raises(KeyError):
        ledger.adjust_incoming_rate("NOPE", 70)


@pytest.mark.parametrize(
    "build",
    [
        lambda: PurchaseReceipt("PR-1", on(1), "Milk", WAREHOUSE, 0, 50),
        lambda: PurchaseReceipt("PR-1", on(1), "Milk", WAREHOUSE, -5, 50),
        lambda: DeliveryNote("DN-1", on(1), "Milk", WAREHOUSE, 0),
        lambda: DeliveryNote("DN-1", on(1), "Milk", WAREHOUSE, -5),
        lambda: Manufacture("SE-1", on(1), WAREHOUSE, {"Milk": 5}, "Milk Powder", 0),
        lambda: Manufacture("SE-1", on(1), WAREHOUSE, {"Milk": 0}, "Milk Powder", 1),
    ],
)
def test_quantities_must_be_more_than_zero(build):
    with pytest.raises(ValueError, match="more than zero"):
        build()


# Random ledgers checked against a rebuild from scratch

BOMS = {
    "Milk Powder": {"Milk": 10, "Sugar": 1},
    "Malted Milk": {"Milk Powder": 2, "Sugar": 1},
}
START = datetime(2026, 1, 1, 9)
RATE_STEP = Decimal("0.000000001")


def rebuild(ledger):
    """Value every live entry from scratch in posting order, without the repost engine.

    Returns the expected balances per entry and the expected rates and amounts on the vouchers.
    """
    queues = defaultdict(list)
    consumed = {}
    expected, fields = {}, {}
    live = sorted((sle for sle in ledger.entries.values() if not sle.is_cancelled), key=lambda s: s.sort_key)

    for sle in live:
        voucher = ledger.vouchers[sle.voucher_no]
        queue = queues[sle.key]
        value_before = sum(qty * rate for qty, rate in queue)

        if sle.actual_qty > 0:
            if isinstance(voucher, Manufacture):
                cost = sum(consumed[row.name] for row in voucher.raw_material_rows)
                rate = (cost / sle.actual_qty).quantize(RATE_STEP, ROUND_HALF_UP)
                fields[voucher.name] = ([consumed[row.name] for row in voucher.raw_material_rows], rate)
            else:
                rate = voucher.valuation_rate
            if queue and queue[-1][1] == rate:
                queue[-1][0] += sle.actual_qty
            else:
                queue.append([sle.actual_qty, rate])
        else:
            needed = -sle.actual_qty
            while needed:
                taken = min(needed, queue[0][0])
                needed -= taken
                queue[0][0] -= taken
                if not queue[0][0]:
                    queue.pop(0)

        value = sum(qty * rate for qty, rate in queue)
        consumed[sle.voucher_detail_no] = value_before - value
        if isinstance(voucher, DeliveryNote):
            fields[voucher.name] = (consumed[sle.voucher_detail_no] / voucher.qty).quantize(
                RATE_STEP, ROUND_HALF_UP
            )
        expected[sle.name] = (
            sum(qty for qty, _ in queue),
            value,
            value - value_before,
            [list(b) for b in queue],
        )

    return expected, fields


def voucher_fields(ledger):
    """The same rates and amounts as rebuild() works out, as the repost wrote them to the vouchers."""
    fields = {}
    for voucher in ledger.vouchers.values():
        if not ledger.voucher_entries(voucher.name):
            continue
        if isinstance(voucher, DeliveryNote):
            fields[voucher.name] = voucher.incoming_rate
        elif isinstance(voucher, Manufacture):
            fields[voucher.name] = (
                [row.basic_amount for row in voucher.raw_material_rows],
                voucher.finished_item_row.basic_rate,
            )
    return fields


def random_voucher(rng, name, when, stock):
    """A random voucher that `stock` (quantity on hand per item) can support."""
    choices = ["receipt"]
    if any(stock.values()):
        choices.append("delivery")
    makeable = [fg for fg, bom in BOMS.items() if all(stock[i] >= q for i, q in bom.items())]
    if makeable:
        choices.append("manufacture")

    kind = rng.choice(choices)
    if kind == "receipt":
        item = rng.choice(["Milk", "Sugar"])
        voucher_class = rng.choice([PurchaseReceipt, MaterialReceipt])
        return voucher_class(name, when, item, WAREHOUSE, rng.randint(5, 40), rng.randint(20, 90))
    if kind == "delivery":
        item = rng.choice([item for item, qty in stock.items() if qty])
        return DeliveryNote(name, when, item, WAREHOUSE, rng.randint(1, stock[item]))

    finished_item = rng.choice(makeable)
    bom = BOMS[finished_item]
    fg_qty = rng.randint(1, min(min(stock[i] // q for i, q in bom.items()), 3))
    return Manufacture(name, when, WAREHOUSE, {i: q * fg_qty for i, q in bom.items()}, finished_item, fg_qty)


def stock_at(ledger, when):
    stock = defaultdict(int)
    for sle in ledger.entries.values():
        if not sle.is_cancelled and sle.posting_datetime <= when:
            stock[sle.item_code] += int(sle.actual_qty)
    return stock


def random_ledger(rng):
    ledger = StockLedger()
    for n in range(rng.randint(10, 30)):
        # Two vouchers per hour, so some share a posting time
        when = START + timedelta(hours=n // 2)
        ledger.submit(random_voucher(rng, f"V-{n:03d}", when, stock_at(ledger, when)))
    return ledger


def random_change(rng, ledger):
    """Apply one random change, trying up to five times if the quantity check refuses it.

    Returns the RepostResult, or None if every attempt was refused. A refusal must leave the ledger
    as it was.
    """
    live = [v for v in ledger.vouchers.values() if ledger.voucher_entries(v.name)]
    receipts = [v for v in live if isinstance(v, Receipt)]
    kind = rng.choice(["rate", "rate", "insert", "cancel"] if receipts else ["insert", "cancel"])

    for _ in range(5):
        before = (len(ledger.entries), balances(ledger))
        try:
            if kind == "rate":
                return ledger.adjust_incoming_rate(rng.choice(receipts).name, rng.randint(20, 90))
            if kind == "insert":
                times = [v.posting_datetime for v in ledger.vouchers.values()]
                when = (
                    rng.choice(times)
                    if rng.random() < 0.5
                    else START + timedelta(minutes=rng.randint(0, 900))
                )
                voucher = random_voucher(rng, f"X-{len(ledger.vouchers):03d}", when, stock_at(ledger, when))
                return ledger.submit(voucher)
            manufactures = [v for v in live if isinstance(v, Manufacture)]
            pool = manufactures if manufactures and rng.random() < 0.5 else live
            return ledger.cancel(rng.choice(pool).name)
        except NegativeStockError:
            assert (len(ledger.entries), balances(ledger)) == before
    return None


def assert_matches_rebuild(ledger):
    expected, fields = rebuild(ledger)
    assert balances(ledger) == expected
    assert voucher_fields(ledger) == fields


@pytest.mark.parametrize("seed", range(300))
def test_repost_matches_a_rebuild_from_scratch(seed):
    rng = random.Random(seed)
    ledger = random_ledger(rng)
    assert_matches_rebuild(ledger)

    for _ in range(rng.randint(1, 3)):
        gl_before = {
            name: gl_entries(ledger, name) for name in ledger.vouchers if ledger.voucher_entries(name)
        }

        result = random_change(rng, ledger)
        if result is None:
            continue

        assert_matches_rebuild(ledger)

        # Entries are valued once each, in posting order
        keys = [ledger.entries[name].sort_key for name in result.processed]
        assert keys == sorted(set(keys))

        # Every voucher whose GL moved is on the list for a GL repost
        for name, before in gl_before.items():
            after = gl_entries(ledger, name)
            assert sum(after.values()) == 0
            if after != before:
                assert name in result.affected_vouchers
