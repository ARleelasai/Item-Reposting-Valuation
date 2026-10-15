from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .fifo import round_rate, to_decimal


def positive_qty(value) -> Decimal:
    qty = to_decimal(value)
    if qty <= 0:
        raise ValueError(f"Quantity must be more than zero, got {qty}")
    return qty


class Voucher:
    voucher_type = ""
    # Account on the other side of the stock account in this voucher's GL entries
    counter_account = ""

    def __init__(self, name: str, posting_datetime: datetime):
        self.name = name
        self.posting_datetime = posting_datetime

    def get_sl_entries(self) -> list[dict]:
        raise NotImplementedError

    def incoming_rate_for(self, sle) -> Decimal:
        """Rate for an entry flagged recalculate_rate, worked out from the voucher's current values."""
        raise NotImplementedError(f"{self.voucher_type} {self.name} has no recalculated rows")

    def set_outgoing_value(self, sle, value: Decimal):
        """Called by the repost when the value an outgoing entry consumed has changed."""


class Receipt(Voucher):
    def __init__(self, name, posting_datetime, item_code, warehouse, qty, rate):
        super().__init__(name, posting_datetime)
        self.item_code = item_code
        self.warehouse = warehouse
        self.qty = positive_qty(qty)
        self.rate = to_decimal(rate)
        # What the stock is valued at. It can move later (landed cost, invoice rate difference)
        # while `rate` stays what the document said.
        self.valuation_rate = round_rate(self.rate)

    def get_sl_entries(self):
        return [
            {
                "item_code": self.item_code,
                "warehouse": self.warehouse,
                "voucher_detail_no": f"{self.name}-1",
                "actual_qty": self.qty,
                "incoming_rate": self.valuation_rate,
            }
        ]

    def incoming_rate_for(self, sle):
        return self.valuation_rate


class MaterialReceipt(Receipt):
    voucher_type = "Stock Entry"

    def __init__(self, name, posting_datetime, item_code, warehouse, qty, rate, is_opening=True):
        super().__init__(name, posting_datetime, item_code, warehouse, qty, rate)
        # An opening entry cannot hit a P&L account, so it goes against Temporary Opening
        self.counter_account = "Temporary Opening" if is_opening else "Stock Adjustment"


class PurchaseReceipt(Receipt):
    voucher_type = "Purchase Receipt"
    counter_account = "Stock Received But Not Billed"


class DeliveryNote(Voucher):
    voucher_type = "Delivery Note"
    counter_account = "Cost of Goods Sold"

    def __init__(self, name, posting_datetime, item_code, warehouse, qty):
        super().__init__(name, posting_datetime)
        self.item_code = item_code
        self.warehouse = warehouse
        self.qty = positive_qty(qty)
        # Delivery Note Item.incoming_rate: cost per unit of what went out
        self.incoming_rate = None

    def get_sl_entries(self):
        return [
            {
                "item_code": self.item_code,
                "warehouse": self.warehouse,
                "voucher_detail_no": f"{self.name}-1",
                "actual_qty": -self.qty,
            }
        ]

    def set_outgoing_value(self, sle, value):
        self.incoming_rate = round_rate(value / self.qty)


@dataclass
class StockEntryDetail:
    name: str
    item_code: str
    qty: Decimal
    is_finished_item: bool = False
    basic_rate: Decimal | None = None
    basic_amount: Decimal | None = None


class Manufacture(Voucher):
    voucher_type = "Stock Entry"
    counter_account = "Stock Adjustment"

    def __init__(self, name, posting_datetime, warehouse, raw_materials: dict, finished_item: str, fg_qty):
        super().__init__(name, posting_datetime)
        if finished_item in raw_materials:
            raise ValueError(f"{finished_item} cannot be both consumed and produced by {name}")

        self.warehouse = warehouse
        self.items = [
            StockEntryDetail(f"{name}-{idx}", item_code, positive_qty(qty))
            for idx, (item_code, qty) in enumerate(raw_materials.items(), 1)
        ]
        self.items.append(
            StockEntryDetail(
                f"{name}-{len(self.items) + 1}", finished_item, positive_qty(fg_qty), is_finished_item=True
            )
        )

    @property
    def raw_material_rows(self) -> list[StockEntryDetail]:
        return self.items[:-1]

    @property
    def finished_item_row(self) -> StockEntryDetail:
        return self.items[-1]

    def get_sl_entries(self):
        fg = self.finished_item_row
        # Raw materials go first. The finished good is valued from what they consumed, so its entry
        # has to sort after theirs.
        entries = [
            {
                "item_code": row.item_code,
                "warehouse": self.warehouse,
                "voucher_detail_no": row.name,
                "actual_qty": -row.qty,
                "dependant_sle_voucher_detail_no": fg.name,
            }
            for row in self.raw_material_rows
        ]
        entries.append(
            {
                "item_code": fg.item_code,
                "warehouse": self.warehouse,
                "voucher_detail_no": fg.name,
                "actual_qty": fg.qty,
                "recalculate_rate": True,
            }
        )
        return entries

    def set_outgoing_value(self, sle, value):
        row = next(row for row in self.raw_material_rows if row.name == sle.voucher_detail_no)
        row.basic_amount = value
        row.basic_rate = round_rate(value / row.qty)

    def incoming_rate_for(self, sle):
        fg = self.finished_item_row
        raw_material_cost = sum(row.basic_amount for row in self.raw_material_rows)
        fg.basic_rate = round_rate(raw_material_cost / fg.qty)
        fg.basic_amount = fg.basic_rate * fg.qty
        return fg.basic_rate
