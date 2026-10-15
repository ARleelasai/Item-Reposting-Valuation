import bisect
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .fifo import ZERO, NegativeStockError, round_rate, to_decimal
from .repost import RepostResult, repost
from .vouchers import Receipt, Voucher


@dataclass(eq=False)
class StockLedgerEntry:
    name: str
    item_code: str
    warehouse: str
    posting_datetime: datetime
    creation: int
    seq: int
    voucher_type: str
    voucher_no: str
    voucher_detail_no: str
    actual_qty: Decimal
    incoming_rate: Decimal = ZERO
    recalculate_rate: bool = False
    dependant_sle_voucher_detail_no: str | None = None
    is_cancelled: bool = False

    # Running balance after this entry. None until the entry has been valued once.
    qty_after_transaction: Decimal | None = None
    stock_value: Decimal | None = None
    valuation_rate: Decimal | None = None
    stock_value_difference: Decimal | None = None
    stock_queue: list | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.item_code, self.warehouse)

    @property
    def sort_key(self) -> tuple:
        # creation breaks ties between vouchers posted at the same time, seq between rows of one voucher
        return (self.posting_datetime, self.creation, self.seq)


def _sort_key(sle):
    return sle.sort_key


class StockLedger:
    def __init__(self):
        self.entries: dict[str, StockLedgerEntry] = {}
        self.vouchers: dict[str, Voucher] = {}
        # (item_code, warehouse) -> live entries in posting order
        self._live = defaultdict(list)
        self._by_detail_no: dict[str, StockLedgerEntry] = {}

    def submit(self, voucher: Voucher) -> RepostResult:
        if voucher.name in self.vouchers:
            raise ValueError(f"{voucher.name} is already submitted")

        creation = len(self.vouchers) + 1
        new_entries = [
            StockLedgerEntry(
                name=f"SLE-{len(self.entries) + seq:05d}",
                posting_datetime=voucher.posting_datetime,
                creation=creation,
                seq=seq,
                voucher_type=voucher.voucher_type,
                voucher_no=voucher.name,
                **row,
            )
            for seq, row in enumerate(voucher.get_sl_entries(), 1)
        ]
        self._validate_future_qty(added=new_entries)

        self.vouchers[voucher.name] = voucher
        for sle in new_entries:
            self.entries[sle.name] = sle
            self._by_detail_no[sle.voucher_detail_no] = sle
            bisect.insort(self._live[sle.key], sle, key=_sort_key)

        return repost(self, new_entries)

    def cancel(self, voucher_no: str) -> RepostResult:
        cancelled = self._live_voucher_entries(voucher_no)
        self._validate_future_qty(removed=cancelled)

        for sle in cancelled:
            self._live[sle.key].remove(sle)
            sle.is_cancelled = True

        # The cancelled rows are out of the ledger, so revaluation starts at whatever now follows them
        starts = [self._first_after(sle.key, sle.sort_key) for sle in cancelled]
        result = repost(self, [sle for sle in starts if sle])
        # Its GL entries go away, so it needs the same GL repost as a voucher whose value moved
        result.affected_vouchers.insert(0, voucher_no)
        return result

    def adjust_incoming_rate(self, voucher_no: str, rate, full_replay=False) -> RepostResult:
        """Revalue a receipt, e.g. when its Purchase Invoice comes in at a different rate.

        The receipt's own `rate` is what the document said and stays as it is. Only the valuation
        rate moves, and the repost picks it up through recalculate_rate.
        """
        voucher = self.vouchers[voucher_no]
        if not isinstance(voucher, Receipt):
            raise TypeError(f"{voucher.voucher_type} {voucher_no} is not a receipt")

        entries = self._live_voucher_entries(voucher_no)
        voucher.valuation_rate = round_rate(to_decimal(rate))
        for sle in entries:
            sle.recalculate_rate = True
        return repost(self, entries, full_replay=full_replay)

    def voucher_entries(self, voucher_no: str) -> list[StockLedgerEntry]:
        return [sle for sle in self.entries.values() if sle.voucher_no == voucher_no and not sle.is_cancelled]

    def entries_for(self, item_code: str, warehouse: str) -> list[StockLedgerEntry]:
        return list(self._live.get((item_code, warehouse), []))

    def previous_sle(self, sle: StockLedgerEntry) -> StockLedgerEntry | None:
        entries = self._live[sle.key]
        idx = bisect.bisect_left(entries, sle.sort_key, key=_sort_key)
        return entries[idx - 1] if idx else None

    def next_sle(self, sle: StockLedgerEntry) -> StockLedgerEntry | None:
        return self._first_after(sle.key, sle.sort_key)

    def sle_by_detail_no(self, voucher_detail_no: str) -> StockLedgerEntry:
        return self._by_detail_no[voucher_detail_no]

    def _live_voucher_entries(self, voucher_no: str) -> list[StockLedgerEntry]:
        if voucher_no not in self.vouchers:
            raise KeyError(f"Unknown voucher {voucher_no}")
        entries = self.voucher_entries(voucher_no)
        if not entries:
            raise ValueError(f"{voucher_no} is already cancelled")
        return entries

    def _first_after(self, key, sort_key) -> StockLedgerEntry | None:
        entries = self._live.get(key, [])
        idx = bisect.bisect_right(entries, sort_key, key=_sort_key)
        return entries[idx] if idx < len(entries) else None

    def _validate_future_qty(self, added=(), removed=()):
        """Refuse a change that takes an item-warehouse below zero on any date.

        Runs before anything is written, so a refusal leaves the ledger untouched.
        """
        removed_names = {sle.name for sle in removed}
        for key in {sle.key for sle in (*added, *removed)}:
            rows = [sle for sle in self._live.get(key, []) if sle.name not in removed_names]
            rows += [sle for sle in added if sle.key == key]

            balance = ZERO
            for sle in sorted(rows, key=_sort_key):
                balance += sle.actual_qty
                if balance < 0:
                    raise NegativeStockError(
                        f"{sle.item_code} in {sle.warehouse} would be {balance} on "
                        f"{sle.posting_datetime:%d %b %Y} ({sle.voucher_no})"
                    )
