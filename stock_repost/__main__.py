from .gl import gl_entries
from .scenario import EDITED_RECEIPT, NEW_RATE, build_ledger


def fmt_amount(value) -> str:
    return f"{value:,.2f}"


def fmt_queue(queue) -> str:
    return "[" + ", ".join(f"[{qty.normalize():f}, {rate.normalize():f}]" for qty, rate in queue) + "]"


def fmt_change(before, after) -> str:
    if before == after:
        return fmt_amount(after)
    return f"{fmt_amount(before)} -> {fmt_amount(after)}"


def fmt_gl(amount) -> str:
    if not amount:
        return "-"
    return f"{fmt_amount(abs(amount))} {'Dr' if amount > 0 else 'Cr'}"


def main():
    ledger = build_ledger()
    before = {sle.name: (sle.stock_value_difference, sle.stock_value) for sle in ledger.entries.values()}
    gl_before = {voucher_no: gl_entries(ledger, voucher_no) for voucher_no in ledger.vouchers}

    receipt = ledger.vouchers[EDITED_RECEIPT]
    result = ledger.adjust_incoming_rate(EDITED_RECEIPT, NEW_RATE)

    print(
        f"{EDITED_RECEIPT} ({receipt.item_code}, {receipt.posting_datetime:%d %b}) revalued "
        f"from {receipt.rate:f} to {receipt.valuation_rate.normalize():f}\n"
    )
    print(
        f"{'Date':<7}{'Item':<13}{'Voucher':<20}{'Qty':>5}  {'Value moved':<25}"
        f"{'Balance value':<23}FIFO queue after"
    )
    for sle in sorted(ledger.entries.values(), key=lambda s: s.sort_key):
        svd, value = before[sle.name]
        date = f"{sle.posting_datetime:%d %b}"
        print(
            f"{date:<7}{sle.item_code:<13}{sle.voucher_no:<20}{sle.actual_qty.normalize():>+5f}  "
            f"{fmt_change(svd, sle.stock_value_difference):<25}"
            f"{fmt_change(value, sle.stock_value):<23}{fmt_queue(sle.stock_queue)}"
        )

    print(
        f"\nRepost valued {len(result.processed)} of {len(ledger.entries)} entries; "
        f"stock value moved on {', '.join(result.affected_vouchers)}\n"
    )

    print("GL entries that change")
    for voucher_no in result.affected_vouchers:
        old, new = gl_before[voucher_no], gl_entries(ledger, voucher_no)
        if old == new:
            print(f"  {voucher_no:<19} no change")
            continue
        for account in sorted(set(old) | set(new)):
            print(
                f"  {voucher_no:<19} {account:<30} {fmt_gl(old.get(account, 0)):>12} -> "
                f"{fmt_gl(new.get(account, 0))}"
            )


if __name__ == "__main__":
    main()
