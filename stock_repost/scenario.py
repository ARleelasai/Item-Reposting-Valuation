from datetime import datetime

from .ledger import StockLedger
from .vouchers import DeliveryNote, Manufacture, MaterialReceipt, PurchaseReceipt

WAREHOUSE = "Stores"
EDITED_RECEIPT = "MAT-PRE-2026-00001"
NEW_RATE = 80


def on(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 1, day, hour)


def build_ledger() -> StockLedger:
    """The January transactions from the assignment. Both items are valued FIFO."""
    ledger = StockLedger()
    ledger.submit(MaterialReceipt("MAT-STE-2026-00001", on(1, 9), "Milk", WAREHOUSE, 100, 50))
    ledger.submit(PurchaseReceipt(EDITED_RECEIPT, on(10), "Milk", WAREHOUSE, 50, 60))
    ledger.submit(DeliveryNote("MAT-DN-2026-00001", on(15), "Milk", WAREHOUSE, 80))
    ledger.submit(PurchaseReceipt("MAT-PRE-2026-00002", on(20), "Milk", WAREHOUSE, 50, 60))
    ledger.submit(Manufacture("MAT-STE-2026-00002", on(21), WAREHOUSE, {"Milk": 100}, "Milk Powder", 10))
    ledger.submit(DeliveryNote("MAT-DN-2026-00002", on(25), "Milk Powder", WAREHOUSE, 10))
    return ledger
