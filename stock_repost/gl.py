from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

CURRENCY_PRECISION = Decimal("0.01")
STOCK_ACCOUNT = "Stock In Hand"


def gl_entries(ledger, voucher_no: str) -> dict[str, Decimal]:
    """Net amount per account for one voucher, positive for debit and negative for credit.

    Each entry posts its stock_value_difference to the stock account and the opposite to the
    voucher's counter account, and amounts on one account are netted, as ERPNext merges similar GL
    entries. In the January case Milk out and Milk Powder in are equal, so the Manufacture nets to
    nothing.
    """
    voucher = ledger.vouchers[voucher_no]

    totals = defaultdict(Decimal)
    for sle in ledger.voucher_entries(voucher_no):
        amount = sle.stock_value_difference.quantize(CURRENCY_PRECISION, rounding=ROUND_HALF_UP)
        totals[STOCK_ACCOUNT] += amount
        totals[voucher.counter_account] -= amount

    return {account: amount for account, amount in totals.items() if amount}
