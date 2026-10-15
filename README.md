# Stock reposting for FIFO: Milk and Milk Powder

A backdated rate change on one Purchase Receipt changes the cost of everything that later consumed that stock, including stock of other items made from it. This repo works through the assignment case:

- the 10 Jan Milk receipt moves from ₹60/L to ₹80/L;
- the change flows through FIFO, into the Milk Powder made on 21 Jan, and out through the 25 Jan delivery.

It contains a small reposting engine built on the same ideas as ERPNext's stock ledger, with tests that pin every number. The full write-up, with the ERPNext v15 code paths behind each answer, is in [docs/notes.md](docs/notes.md).

## The change in numbers

| Date | Entry | Before (₹60) | After (₹80) | What moved |
|---|---|---|---|---|
| 01 Jan | Opening, Milk +100 L @ 50 | 5,000 | 5,000 | nothing |
| 10 Jan | Purchase Receipt, Milk +50 L | +3,000 | **+4,000** | the change itself |
| 15 Jan | Delivery Note, Milk -80 L | -4,000 | -4,000 | only the balance (4,000 -> 5,000) |
| 20 Jan | Purchase Receipt, Milk +50 L @ 60 | +3,000 | +3,000 | only the balance (7,000 -> 8,000) |
| 21 Jan | Manufacture, Milk -100 L | -5,800 | **-6,800** | 20@50 + 50@80 + 30@60 |
| 21 Jan | Manufacture, Milk Powder +10 kg | 580/kg | **680/kg** | rate follows the milk consumed |
| 25 Jan | Delivery Note, Milk Powder -10 kg | -5,800 | **-6,800** | COGS +1,000 |

Milk closes at 20 L @ 60 = 1,200 either way. The extra ₹1,000 enters stock on 10 Jan and leaves as cost of goods sold on 25 Jan.

## Run it

Python 3.10 or newer. Nothing to install apart from pytest.

```bash
pip install pytest
pytest -q
python -m stock_repost
```

`python -m stock_repost` builds the January ledger, revalues the 10 Jan receipt to ₹80 and prints:

```
MAT-PRE-2026-00001 (Milk, 10 Jan) revalued from 60 to 80

Date   Item         Voucher               Qty  Value moved              Balance value          FIFO queue after
01 Jan Milk         MAT-STE-2026-00001   +100  5,000.00                 5,000.00               [[100, 50]]
10 Jan Milk         MAT-PRE-2026-00001    +50  3,000.00 -> 4,000.00     8,000.00 -> 9,000.00   [[100, 50], [50, 80]]
15 Jan Milk         MAT-DN-2026-00001     -80  -4,000.00                4,000.00 -> 5,000.00   [[20, 50], [50, 80]]
20 Jan Milk         MAT-PRE-2026-00002    +50  3,000.00                 7,000.00 -> 8,000.00   [[20, 50], [50, 80], [50, 60]]
21 Jan Milk         MAT-STE-2026-00002   -100  -5,800.00 -> -6,800.00   1,200.00               [[20, 60]]
21 Jan Milk Powder  MAT-STE-2026-00002    +10  5,800.00 -> 6,800.00     5,800.00 -> 6,800.00   [[10, 680]]
25 Jan Milk Powder  MAT-DN-2026-00002     -10  -5,800.00 -> -6,800.00   0.00                   []

Repost valued 6 of 7 entries; stock value moved on MAT-PRE-2026-00001, MAT-STE-2026-00002, MAT-DN-2026-00002

GL entries that change
  MAT-PRE-2026-00001  Stock In Hand                   3,000.00 Dr -> 4,000.00 Dr
  MAT-PRE-2026-00001  Stock Received But Not Billed   3,000.00 Cr -> 4,000.00 Cr
  MAT-STE-2026-00002  no change
  MAT-DN-2026-00002   Cost of Goods Sold              5,800.00 Dr -> 6,800.00 Dr
  MAT-DN-2026-00002   Stock In Hand                   5,800.00 Cr -> 6,800.00 Cr
```

## Answers

| Question | Short answer | Details |
|---|---|---|
| 1. Which transactions are affected | Every Milk entry from 10 Jan, and Milk Powder through the 21 Jan Manufacture. Cost moves only on the 10 Jan receipt, the 21 Jan Manufacture and the 25 Jan delivery. | [notes, section 1](docs/notes.md#1-which-transactions-are-affected) |
| 2. How the later valuation is recalculated | Replay FIFO from the queue stored before 10 Jan, then value Milk Powder from the new consumption. | [notes, section 2](docs/notes.md#2-how-the-later-valuation-is-recalculated) |
| 3. Reposting design for FIFO | One heap of entries in posting order. Stop on an item-warehouse once its queue matches what was stored. | [notes, section 3](docs/notes.md#3-reposting-design-for-fifo) |
| 4. Running balance on every entry | Write amplification, locks, a stale window, partial failure, closed periods, ordering drift. | [notes, section 4](docs/notes.md#4-problems-with-a-running-balance-on-every-entry) |

The 15 Jan delivery keeps its cost: FIFO took all 80 L from the opening 100 L @ 50. Its stored balance still changes, so the row is rewritten.

## Design decisions

| Decision | Reason |
|---|---|
| One heap across item-warehouses | Milk Powder is valued only after the Milk it consumed is final, so nothing is valued twice. ERPNext v16 does the same with one sorted queue. |
| Stop when the FIFO queue matches | Later entries would come out the same. `full_replay=True` walks to the end, for repairing a ledger whose stored balances are suspect. |
| Quantity check before any write | A cancel or backdated entry that leaves stock negative on a later date is refused with the ledger untouched. Cancelling the 10 Jan receipt fails this way: 21 Jan would need 30 L that is not there. |
| `Decimal` for money | Queues compare with plain equality. Rates that come from a division are rounded to 9 places, as ERPNext's valuation rate is. |
| GL worked out on read | `gl_entries()` derives entries from `stock_value_difference`, so there is no GL repost to model. |
| ERPNext field names | `stock_queue`, `qty_after_transaction`, `dependant_sle_voucher_detail_no` (ERPNext's spelling), so each piece maps onto the real doctype. |
| Rate change as a Purchase Invoice route | A submitted receipt's rate cannot be edited in ERPNext. `adjust_incoming_rate()` moves the valuation rate and leaves the document rate at 60, like an invoice at ₹80 with "Set Landed Cost Based on Purchase Invoice Rate". |

## Limitations

- FIFO only. The notes compare Moving Average, but the code does not implement it. LIFO is not covered.
- Not modelled: serial and batch numbers, returns, Material Transfers, scrap and additional costs on a Manufacture.
- Negative stock is refused. ERPNext can allow it and keeps a negative bin.
- In memory and single process: no locking, background queue or resumable job. The notes cover how ERPNext handles those.

## Layout

| Path | What it is |
|---|---|
| `stock_repost/fifo.py` | `FIFOQueue`: bins of `[qty, rate]`, merge on equal rate, issue from the front |
| `stock_repost/vouchers.py` | Material Receipt, Purchase Receipt, Delivery Note and Manufacture, and what each writes to the ledger |
| `stock_repost/ledger.py` | `StockLedgerEntry` and `StockLedger`: ordering, submit, cancel, `adjust_incoming_rate`, quantity check |
| `stock_repost/repost.py` | the repost walk |
| `stock_repost/gl.py` | GL entries per voucher |
| `stock_repost/scenario.py` | the January transactions from the assignment |
| `tests/` | FIFO unit tests, every scenario number before and after, repost edge cases, and 300 random ledgers checked against a rebuild from scratch |
