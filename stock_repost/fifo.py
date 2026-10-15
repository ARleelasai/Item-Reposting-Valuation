from decimal import ROUND_HALF_UP, Decimal

QTY, RATE = 0, 1
ZERO = Decimal(0)

# ERPNext keeps valuation rates to 9 decimal places
RATE_PRECISION = Decimal("0.000000001")


class NegativeStockError(Exception):
    pass


def to_decimal(value) -> Decimal:
    # via str() so that 0.1 stays 0.1
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round_rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_PRECISION, rounding=ROUND_HALF_UP)


class FIFOQueue:
    """Stock on hand as [qty, rate] bins, oldest first."""

    def __init__(self, bins=None):
        self.bins = [[to_decimal(qty), to_decimal(rate)] for qty, rate in bins or []]

    @property
    def qty(self) -> Decimal:
        return sum((qty for qty, _ in self.bins), ZERO)

    @property
    def value(self) -> Decimal:
        return sum((qty * rate for qty, rate in self.bins), ZERO)

    def add_stock(self, qty, rate):
        qty, rate = to_decimal(qty), to_decimal(rate)
        # Same rate as the newest bin: grow that bin instead of opening a new one (ERPNext does the same)
        if self.bins and self.bins[-1][RATE] == rate:
            self.bins[-1][QTY] += qty
        else:
            self.bins.append([qty, rate])

    def remove_stock(self, qty) -> list[list[Decimal]]:
        """Take `qty` out of the oldest bins and return what was taken as [qty, rate] bins.

        Raises NegativeStockError, and leaves the queue untouched, if there is not enough stock.
        """
        qty = to_decimal(qty)
        if qty > self.qty:
            raise NegativeStockError(f"Cannot issue {qty}, only {self.qty} in stock")

        consumed = []
        while qty:
            bin_qty, rate = self.bins[0]
            taken = min(qty, bin_qty)
            consumed.append([taken, rate])
            qty -= taken
            if taken == bin_qty:
                self.bins.pop(0)
            else:
                self.bins[0][QTY] = bin_qty - taken
        return consumed

    def as_list(self) -> list[list[Decimal]]:
        return [list(b) for b in self.bins]

    def __repr__(self):
        return f"FIFOQueue({self.as_list()})"
