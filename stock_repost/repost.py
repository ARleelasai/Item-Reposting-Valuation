import heapq
from dataclasses import dataclass, field

from .fifo import ZERO, FIFOQueue, round_rate


@dataclass
class RepostResult:
    processed: list[str] = field(default_factory=list)
    # entries whose stored balance (queue, qty, value) or value difference came out different
    changed: list[str] = field(default_factory=list)
    # vouchers whose stock value moved; their GL entries need to be made again
    affected_vouchers: list[str] = field(default_factory=list)


def repost(ledger, start_entries, full_replay=False) -> RepostResult:
    """Revalue start_entries and whatever they reach, in posting order.

    Stops on an item-warehouse once its FIFO queue matches what was stored. With full_replay=True
    it walks every item-warehouse it reaches to the end and always revalues the finished good of a
    Manufacture, for ledgers whose stored balances are suspect. Suspect rows of an item-warehouse
    that is not reached still need a start entry of their own.
    """
    result = RepostResult()
    heap, queued = [], set()

    # An entry only pushes later ones: the next entry of its item-warehouse, or the finished good
    # of its own voucher. So entries leave the heap in posting order, each at most once.
    def push(sle):
        if sle and sle.name not in queued:
            queued.add(sle.name)
            heapq.heappush(heap, (sle.sort_key, sle.name))

    for sle in start_entries:
        push(sle)

    while heap:
        _, name = heapq.heappop(heap)
        sle = ledger.entries[name]
        voucher = ledger.vouchers[sle.voucher_no]
        old_queue, old_svd = sle.stock_queue, sle.stock_value_difference

        previous = ledger.previous_sle(sle)
        queue = FIFOQueue(previous.stock_queue if previous else None)
        value_before = queue.value

        if sle.recalculate_rate:
            sle.incoming_rate = voucher.incoming_rate_for(sle)
        if sle.actual_qty > 0:
            queue.add_stock(sle.actual_qty, sle.incoming_rate)
        else:
            queue.remove_stock(-sle.actual_qty)

        sle.qty_after_transaction = queue.qty
        sle.stock_value = queue.value
        sle.valuation_rate = round_rate(queue.value / queue.qty) if queue.qty else ZERO
        sle.stock_value_difference = queue.value - value_before
        sle.stock_queue = queue.as_list()
        result.processed.append(name)

        # A fresh entry has no stored state (None), so it always counts as changed
        queue_changed = old_queue != sle.stock_queue
        svd_changed = old_svd != sle.stock_value_difference
        if queue_changed or svd_changed:
            result.changed.append(name)

        if svd_changed and sle.voucher_no not in result.affected_vouchers:
            result.affected_vouchers.append(sle.voucher_no)

        if svd_changed or full_replay:
            if sle.actual_qty < 0:
                voucher.set_outgoing_value(sle, -sle.stock_value_difference)
            if sle.dependant_sle_voucher_detail_no:
                push(ledger.sle_by_detail_no(sle.dependant_sle_voucher_detail_no))

        if queue_changed or full_replay:
            push(ledger.next_sle(sle))

    return result
