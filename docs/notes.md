# FIFO Reposting After a Backdated Rate Change

**Project:** ERPNext Stock Valuation
**Module:** Stock
**Feature:** Reposting the stock ledger when a past Purchase Receipt is revalued
**Tested On / Version:** Python 3.10 model; ERPNext behaviour read from the v15.50.0 source
**Prepared By:** leelasai
**Date:** 2026-10-13

---

## Overview

This document answers the four questions in the assignment and explains the model in this repo. The worked case:

- the 10 Jan Milk Purchase Receipt is revalued from ₹60/L to ₹80/L;
- Milk is consumed by a Manufacture on 21 Jan that produces Milk Powder;
- that Milk Powder is delivered on 25 Jan.

ERPNext references are to v15.50.0, with permalinks in the [ERPNext mapping](#erpnext-mapping) table at the end.

### Assumptions

| # | Assumption |
|---|---|
| 1 | One warehouse, `Stores`, which maps to one `Stock In Hand` account |
| 2 | Milk and Milk Powder both use FIFO |
| 3 | The opening stock is a Material Receipt with `is_opening = Yes`, against Temporary Opening |
| 4 | The Manufacture has no additional costs, no scrap and no manual rate on the finished good |
| 5 | Allow Negative Stock is off, which is the default |
| 6 | The rate change arrives as a Purchase Invoice at ₹80 with "Set Landed Cost Based on Purchase Invoice Rate" on (see [How the edit happens in ERPNext](#how-the-edit-happens-in-erpnext)) |

---

## 1. Which Transactions Are Affected

Every Milk entry from 10 Jan onwards is touched, plus the Milk Powder entries reached through the 21 Jan Manufacture. Only three vouchers end up with a different cost: the 10 Jan receipt, the 21 Jan Manufacture and the 25 Jan delivery. The other two rows change their stored balance but not their cost.

### Stock Ledger Entries

| Date | Entry | Field | Before | After | Why |
|---|---|---|---|---|---|
| 10 Jan | PR, Milk +50 | `incoming_rate` / `stock_value_difference` | 60 / 3,000 | 80 / 4,000 | the change itself |
| 10 Jan | PR, Milk +50 | `stock_value` / `valuation_rate` / `stock_queue` | 8,000 / 53.33 / `[[100,50],[50,60]]` | 9,000 / 60 / `[[100,50],[50,80]]` | new layer at 80 |
| 15 Jan | DN, Milk -80 | `stock_value_difference` | -4,000 | -4,000 | FIFO took all 80 L from the opening layer @ 50 |
| 15 Jan | DN, Milk -80 | `stock_value` / `valuation_rate` / `stock_queue` | 4,000 / 57.14 / `[[20,50],[50,60]]` | 5,000 / 71.43 / `[[20,50],[50,80]]` | the 80 layer is still in stock |
| 20 Jan | PR, Milk +50 | `stock_value_difference` | 3,000 | 3,000 | its own rate is still 60 |
| 20 Jan | PR, Milk +50 | `stock_value` / `valuation_rate` / `stock_queue` | 7,000 / 58.33 / `[[20,50],[100,60]]` | 8,000 / 66.67 / `[[20,50],[50,80],[50,60]]` | before, it merged into the 60 layer; now the 80 layer sits between |
| 21 Jan | SE, Milk -100 | `stock_value_difference` | -5,800 | -6,800 | 20@50 + 50@80 + 30@60 |
| 21 Jan | SE, Milk -100 | `stock_value` / `stock_queue` | 1,200 / `[[20,60]]` | 1,200 / `[[20,60]]` | the 80 layer is used up, so Milk's queue is back to what it was |
| 21 Jan | SE, Milk Powder +10 | `incoming_rate` / `stock_value_difference` / `stock_value` | 580 / 5,800 / 5,800 | 680 / 6,800 / 6,800 | finished good = milk consumed / 10 kg |
| 25 Jan | DN, Milk Powder -10 | `stock_value_difference` | -5,800 | -6,800 | the whole 680 layer goes out |

### Voucher Fields

| Document | Field | Before | After |
|---|---|---|---|
| Purchase Receipt Item (10 Jan) | `valuation_rate` | 60 | 80 |
| Purchase Receipt Item (10 Jan) | `rate`, `amount` | 60, 3,000 | unchanged |
| Purchase Receipt Item (10 Jan) | `rate_difference_with_purchase_invoice` | 0 | 1,000 |
| Stock Entry Detail, Milk row | `basic_rate` | 58 | 68 |
| Stock Entry Detail, Milk Powder row | `basic_rate` / `valuation_rate` / `amount` | 580 / 580 / 5,800 | 680 / 680 / 6,800 |
| Stock Entry | `total_outgoing_value` / `total_incoming_value` | 5,800 / 5,800 | 6,800 / 6,800 |
| Delivery Note Item (25 Jan) | `incoming_rate` | 580 | 680 |
| Delivery Note Item (15 Jan) | `incoming_rate` | 50 | unchanged |

> Note: on v15 the Milk row of the Stock Entry gets `basic_rate` 68, but its `basic_amount` and `amount` stay 5,800 in the database. `update_rate_on_stock_entry` sets only `basic_rate` on a raw-material row that feeds a finished good. The later `recalculate_amounts_in_stock_entry` saves only the finished-good row and the header.

### GL Entries

| Voucher | Account | Before | After |
|---|---|---|---|
| PR 10 Jan | Stock In Hand | Dr 3,000 | Dr 4,000 |
| PR 10 Jan | Stock Received But Not Billed | Cr 3,000 | Cr 4,000 |
| DN 15 Jan | Cost of Goods Sold / Stock In Hand | 4,000 | unchanged |
| SE 21 Jan | (none) | - | - |
| DN 25 Jan | Cost of Goods Sold | Dr 5,800 | Dr 6,800 |
| DN 25 Jan | Stock In Hand | Cr 5,800 | Cr 6,800 |

The Manufacture posts Milk out and Milk Powder in to the same Stock In Hand account, and Stock Adjustment on both sides. `merge_similar_entries` nets them to zero and drops the lines. If Milk Powder went into a warehouse with its own stock account, this voucher's GL would move from 5,800 to 6,800 as well.

### Not Affected

- The opening entry. It is posted before the change point.
- Every quantity field. Only a rate changed, so `qty_after_transaction` is the same on every row.
- The 15 Jan delivery's cost, its Delivery Note Item `incoming_rate` and its GL.
- The 20 Jan receipt's own rate and value.
- Closing balances: Milk 20 L @ 60 = 1,200, and Milk Powder 0.
- Sales Invoice amounts and receivables. Selling price does not depend on cost.

### Reports Whose Numbers Change

| Report | What moves |
|---|---|
| Stock Ledger | the value columns on the rows above |
| Stock Balance (2-31 Jan) | Milk in-value 6,000 -> 7,000 and out-value 9,800 -> 10,800; Milk Powder in and out 5,800 -> 6,800; closing unchanged |
| General Ledger, Trial Balance | the 10 Jan and 25 Jan entries |
| Profit and Loss | COGS +1,000 for January |
| Balance Sheet as of 10-24 Jan | stock +1,000, until the Milk Powder is delivered |
| Gross Profit | the 25 Jan delivery's buying amount 5,800 -> 6,800 |

A Stock Reconciliation later in the ledger would reset the FIFO queue to its own qty and rate, so value changes would stop there.

---

## How the Edit Happens in ERPNext

A submitted Purchase Receipt's `rate` cannot be edited: the field has no `allow_on_submit`. There are three ways to get to ₹80, and they differ in GL and in whether they work here.

| Route | What changes on the receipt | GL of the 10 Jan receipt | Works here? |
|---|---|---|---|
| Cancel and amend | a new receipt at ₹80 | Dr Stock In Hand 4,000 / Cr SRBNB 4,000 | **No.** Cancelling takes Milk to -30 L on 21 Jan, so `validate_negative_qty_in_future_sle` raises `NegativeStockError` |
| Landed Cost Voucher for ₹1,000 | `landed_cost_voucher_amount` 1,000, `valuation_rate` 80, `rate` stays 60 | Dr Stock In Hand 4,000 / Cr SRBNB 3,000 / Cr the LCV row's expense account (usually Expenses Included In Valuation) 1,000 | Yes. The LCV re-posts the receipt with negative stock allowed |
| Purchase Invoice at ₹80 with Buying Settings "Set Landed Cost Based on Purchase Invoice Rate" | `rate_difference_with_purchase_invoice` 1,000, `valuation_rate` 80, `rate` stays 60 | Dr Stock In Hand 4,000 / Cr SRBNB 4,000 | Yes. This is the route the model follows |

> Important: cancel and amend only works with Allow Negative Stock on, or after cancelling the 21 Jan Manufacture and the 25 Jan delivery first. The amended receipt keeps 10 Jan only if "Edit Posting Date and Time" is ticked; otherwise it posts on today's date.

The Purchase Invoice route needs "Maintain Same Rate Throughout the Purchase Cycle" off. Buying Settings clears the landed-cost flag when that one is on.

### What ERPNext Runs After That

1. The voucher calls `repost_future_sle_and_gle`. With Stock Reposting Settings "Use Item based reposting" on, which is the default, `create_item_wise_repost_entries` creates one Repost Item Valuation per item-warehouse of the voucher (`based_on = "Item and Warehouse"`).
2. The `hourly_long` scheduler runs `repost_entries`. It picks Queued and In Progress entries in posting-date order, then creation, and calls `repost()`.
3. `repost_sl_entries` calls `repost_future_sle`, which works through a list of item-warehouses. For each one, `update_entries_after`:
   - reads the state stored on the entry before the change (`initialize_previous_data`, `get_previous_sle_of_current_voucher`);
   - walks every later entry in `build()`;
   - values each with `process_sle` and `update_queue_values` (`FIFOValuation.add_stock` / `remove_stock`).
4. On the 21 Jan Milk entry, `update_outgoing_rate_on_transaction` -> `update_rate_on_stock_entry` writes `basic_rate` 68 to the Milk row. The entry carries `dependant_sle_voucher_detail_no`, so `get_dependent_entries_to_fix` adds Milk Powder-Stores to the list.
5. In the Milk Powder pass, the 21 Jan entry has `recalculate_rate = 1`. `get_dynamic_incoming_outgoing_rate` calls `recalculate_amounts_in_stock_entry`, and `calculate_rate_and_amount(reset_outgoing_rate=False)` gives 680 through `get_basic_rate_for_manufactured_item`.
6. On the 25 Jan delivery, `update_rate_on_delivery_and_sales_return` writes `incoming_rate` 680.
7. After each item-warehouse, `update_args_in_repost_item_valuation` saves the progress (`current_index`, `affected_transactions`) and commits.
8. `repost_gl_entries` -> `repost_gle_for_stock_vouchers` builds the expected GL for each affected voucher. If `compare_existing_and_expected_gle` finds a difference, it deletes and re-posts that voucher's GL in full.

### What Blocks the Repost

| Check | Where | Effect |
|---|---|---|
| Period Closing Voucher, Closing Stock Balance | `RepostItemValuation.validate_period_closing_voucher` | no repost on or before the closed date |
| Accounting Period | `validate_accounting_period`, called from `make_gl_entries` | the item-wise repost is created without this check, rewrites the stock ledger, then fails at the GL step. The LCV route fails at submit |
| Accounts Frozen Till Date (`acc_frozen_upto`) | `RepostItemValuation.validate_accounts_freeze`, then `check_freezing_date` in the GL step | the frozen-accounts role only gets a warning when the repost is created, but the scheduled job runs as Administrator and the GL step refuses entries on or before the freeze date. The job fails unless a role holder starts it with Start Reposting |
| Stock Frozen Upto / Freeze Stocks Older Than | `StockLedgerEntry.check_stock_frozen_date`, on submit | blocks the LCV route, which re-submits the receipt's entries, unless the user has Role Allowed to Edit Frozen Stock. The invoice route only updates existing entries and is not checked |
| Allow Negative Stock off | `validate_negative_qty_in_future_sle` | blocks cancelling the 10 Jan receipt |

For a closed January, both the LCV and the invoice route are blocked, because both repost from 10 Jan. The usual fix is a Journal Entry in the open period for the ₹1,000, for example Dr COGS / Cr SRBNB.

---

## 2. How the Later Valuation Is Recalculated

Start from the FIFO queue stored on the last entry before the change, then replay every later entry in posting order. Receipts join the back of the queue. Issues take from the front. A finished good is valued from what its raw materials consumed in the same replay.

### The FIFO Walk for Milk

| Date | Entry | Queue before the edit | Queue after the edit | Value out, before -> after |
|---|---|---|---|---|
| 01 Jan | +100 @ 50 | `[[100,50]]` | `[[100,50]]` | |
| 10 Jan | +50 | `[[100,50],[50,60]]` | `[[100,50],[50,80]]` | |
| 15 Jan | -80 | `[[20,50],[50,60]]` | `[[20,50],[50,80]]` | 4,000 -> 4,000 (80@50 both times) |
| 20 Jan | +50 @ 60 | `[[20,50],[100,60]]` | `[[20,50],[50,80],[50,60]]` | |
| 21 Jan | -100 | `[[20,60]]` | `[[20,60]]` | 5,800 -> 6,800 |

Then Milk Powder:

| Date | Entry | Before | After |
|---|---|---|---|
| 21 Jan | +10 kg at (milk consumed / 10) | `[[10,580]]` | `[[10,680]]` |
| 25 Jan | -10 kg | out 5,800 | out 6,800 |

ERPNext merges a receipt into the newest layer when the rates match. That is why the 20 Jan receipt shows `[100,60]` before the edit and a separate `[50,60]` after.

### Finished-Good Rate

ERPNext computes the finished-good rate as (raw materials consumed - scrap value + additional costs) / finished qty. Here that is 6,800 / 10 = 680.

- "Set Basic Rate Manually" is shown only on Repack rows. If it is set on the finished-good row anyway (API or import), the rate stays 580 and the 1,000 difference lands in the Stock Entry's difference account, which defaults to Stock Adjustment.
- A process loss lowers the finished qty and raises the rate.

### Moving Average, for Comparison

Under Moving Average the same edit spreads instead of travelling with one layer:

| Entry | FIFO before -> after | Moving Average before -> after |
|---|---|---|
| 15 Jan DN, Milk out | 4,000 -> 4,000 | 4,266.67 -> 4,800 |
| 21 Jan Milk consumed | 5,800 -> 6,800 | 5,611.11 -> 6,000 |
| Milk Powder rate | 580 -> 680 | 561.11 -> 600 |
| 25 Jan DN, Milk Powder out | 5,800 -> 6,800 | 5,611.11 -> 6,000 |
| Milk closing (20 L) | 1,200 -> 1,200 | 1,122.22 -> 1,200 |

Under FIFO the whole ₹1,000 lands on the 25 Jan delivery. Under Moving Average it splits 533.33 / 388.89 / 77.78 between the 15 Jan delivery, the 25 Jan delivery and Milk's closing stock.

### Changing the Valuation Method Mid-Way

ERPNext does not allow it once the item has submitted transactions:

- `Item.cant_change` blocks it at item level.
- Stock Settings `cant_change_valuation_method` blocks a change of the default for items that have entries.

The stored balances are specific to the method. The Moving Average branch of `process_sle` does not even maintain `stock_queue`. The supported route is a new item with the new method, then a Repack to move the stock across.

---

## 3. Reposting Design for FIFO

Revalue entries from one heap, in posting order. Stop walking an item-warehouse once its FIFO queue matches the stored one again. When a raw material's consumed value moves, queue the finished-good entry of the same Stock Entry.

### The Walk

1. Put the entries that changed directly on a heap ordered by `(posting_datetime, creation, seq)`. These are the revalued receipt, the rows of a new voucher, or the rows right after a cancelled one.
2. Pop the earliest entry. Copy the FIFO queue stored on the entry before it in the same item-warehouse.
3. If the entry has `recalculate_rate`, re-read its incoming rate from the voucher. That applies to a finished good or a revalued receipt.
4. Add or remove the stock. Write `qty_after_transaction`, `stock_value`, `valuation_rate`, `stock_value_difference` and `stock_queue` back to the entry.
5. If `stock_value_difference` moved, the voucher needs its GL rebuilt:
   - write the consumed value back to the voucher (Delivery Note Item `incoming_rate`, Stock Entry Detail `basic_amount`);
   - if the entry has `dependant_sle_voucher_detail_no`, push the finished-good entry.
6. If the new queue differs from the stored one, push the next entry of the same item-warehouse. Otherwise stop there.

### Why It Is Correct

- An entry only pushes entries that sort after itself: the next entry of its item-warehouse, or the finished good of its own voucher, which is emitted after the raw materials. So entries leave the heap in posting order, each at most once. When an entry is valued, the entry before it is already final, and the loop always ends.
- Under FIFO the queue is the whole state. Two entries that start from the same queue and have the same inputs produce the same values. Inputs change only through `recalculate_rate`, and those entries are pushed explicitly, so stopping never skips one that needed work.
- A new entry has no stored queue (`None`), so its first valuation always counts as a change. Without that, a backdated delivery that empties the stock would match an "empty" default and stop too early. `test_backdated_delivery_that_empties_stock` covers this.

### When It Stops

FIFO converges once every layer whose cost changed has been consumed. For Milk that is 21 Jan, when the 50 L @ 80 layer is used up and only 20 L @ 60 from the 20 Jan receipt is left. A Milk entry on 28 Jan would not be looked at; `test_repost_stops_when_the_queue_matches_again` checks that.

Moving Average never converges while qty stays above zero: the difference stays in the average and only shrinks pro rata on each issue. It converges at zero stock or at a Stock Reconciliation.

`full_replay=True` walks every item-warehouse it reaches to the end and always revalues the finished good of a Manufacture, whether or not the raw material's value moved. Use it for repairs, where the stored balances themselves are in doubt. That is what an "Item and Warehouse" repost is often run for in ERPNext. An item-warehouse that nothing reaches still needs a start entry of its own.

### Negative Stock

Quantities do not depend on rates, so `submit` and `cancel` check the future quantity of each touched item-warehouse before writing anything. A change that would go negative on any later date is refused and the ledger is left as it was. ERPNext runs the same kind of check (`validate_negative_qty_in_future_sle`) inside the cancel request.

### Compared with ERPNext

| Aspect | ERPNext v15 | ERPNext v16 | This model |
|---|---|---|---|
| Work list | one item-warehouse at a time; dependants appended to a growing list | one queue of entries sorted across item-warehouses | one heap of entries across item-warehouses |
| Later entries | every later entry is replayed | every later entry is replayed | stops when the FIFO queue matches |
| Progress | commit after each item-warehouse; resume from `current_index` | checkpoint every 2,000 entries | in memory; only the negative-stock refusal is all or nothing |
| GL | expected vs existing compared, re-posted on difference | same | worked out from the ledger on read |
| Locks | `for update` on every later entry | locks in batches of 500 | none (single process) |

### Change Sketch for ERPNext

This is a proposal, not tested on a bench. To stop early inside `update_entries_after.build()`, a few extra rules have to hold because of how v15 queues work:

- Dependent item-warehouses are queued once, at their earliest date. So the walk may stop only when no `recalculate_rate` entry is left later in the same item-warehouse. Otherwise a finished good or transfer target whose input changed could be skipped.
- `deduplicate_similar_repost` skips later queued reposts for the same item-warehouse, assuming the earlier one walked to the end. With an early stop, it has to stop doing that.
- The Bin has to be set from the last entry of the item-warehouse, not the entry where the walk stopped.

```diff
 			while i < len(entries_to_fix):
 				sle = entries_to_fix[i]
 				i += 1

+				stored_queue = json.loads(sle.stock_queue) if sle.stock_queue else None
 				self.process_sle(sle)
 				self.update_bin_data(sle)

 				if sle.dependant_sle_voucher_detail_no:
 					entries_to_fix = self.get_dependent_entries_to_fix(entries_to_fix, sle)
+
+				if i > 1 and self.queue_converged(sle, stored_queue):
+					self.update_bin_from_last_sle()
+					break
```

```python
	def queue_converged(self, sle, stored_queue):
		if stored_queue is None or self.args.get("force_full_replay"):
			return False
		if self.valuation_method != "FIFO" or sle.serial_and_batch_bundle:
			return False
		if sle.voucher_type == "Stock Reconciliation" or self.has_recalculated_entries_after(sle):
			return False

		new_queue = self.wh_data.stock_queue
		return len(new_queue) == len(stored_queue) and all(
			flt(a[0], self.flt_precision) == flt(b[0], self.flt_precision)
			and flt(a[1], self.flt_precision) == flt(b[1], self.flt_precision)
			for a, b in zip(new_queue, stored_queue)
		)
```

The stored queue has to be read before `process_sle`, because `process_sle` overwrites `sle.stock_queue` in place.

---

## 4. Problems With a Running Balance on Every Entry

Under FIFO, the value an issue takes out depends on the history before it. A backdated change therefore needs a forward walk whether or not balances are stored. Storing the balance on every row turns that walk into a write on every later row. It also makes every row depend on the one before it.

| Problem | Cause | What ERPNext does | Mitigation |
|---|---|---|---|
| Write amplification | One edit rewrites every later entry of the item-warehouse and its dependants, the Bin, and the GL of every affected voucher | Each reposted entry is saved in full with `db_update`; the Bin is updated after every entry; `update_qty_in_future_sle` shifts qty on every later row up to the next Stock Reconciliation in one statement; `MAX_WRITES_PER_TRANSACTION *= 4` during reposts | stop once the state converges; write in batches |
| Locks and concurrency | The repost reads and locks later rows while users keep posting to the same item | `for update` on later entries; a timeout leaves the entry In Progress for a retry, a deadlock marks it Failed without the error email; v16 retries both and locks in batches of 500, and with Enable Parallel Reposting on (off by default) runs up to 4 items in parallel, one job per item | short lock batches; one repost per item at a time |
| Stale window | Values are reposted in the background, quantities straight away | Repost Item Valuation runs on the `hourly_long` scheduler; until then values and GL are out of date | show pending reposts; block freezing stock or accounts while one is pending (`check_pending_reposting`) |
| Partial failure | A long job can fail half-way | v15 commits after each item-warehouse and resumes from `current_index`. Milk can be reposted while Milk Powder is not, and entries can be done while the GL is not. Large state goes to a gzipped `reposting_data_file` | resumable, idempotent reposts; reconcile with the Stock Ledger Invariant Check and Stock and Account Value Comparison reports |
| Closed periods and audit | Old rows are updated in place | Reposts are refused before a Period Closing Voucher or Closing Stock Balance, and an Accounting Period stops only the GL step; entries keep no history of old values | post a correction in the open period instead of rewriting history |
| Ordering and drift | Each row is built from "the row before", so a wrong pick (same posting time, wrong tie-break) spoils every row after it | Rows are ordered by `posting_datetime`, then `creation`; v16 fixed several same-timestamp cases and added an opt-in weekly repost of detected variances | a unique ordering key; periodic full replays |
| Row size | The full FIFO queue is stored as JSON on every row | `stock_queue` is a Long Text on each entry | snapshots instead of a queue per row |

What the stored balance buys: the balance as of any date is a single-row read, and a repost starts from one row instead of the beginning of time.

### Alternatives

| Option | How it works | Trade-off |
|---|---|---|
| Periodic snapshots | Store the balance and FIFO queue per item-warehouse at period ends (Closing Stock Balance in v15, Stock Closing Entry in v16) and keep rows as deltas | a repost replays from the nearest snapshot and rewrites fewer rows; reads need snapshot + deltas |
| Forward correction | Post the ₹1,000 difference in the open period instead of revaluing January | no repost and no rewritten history; per-date costs for January stay as they were |

---

## Summary

| Question | Answer |
|---|---|
| Affected transactions | every Milk entry from 10 Jan, the Milk Powder entries via the 21 Jan Manufacture, and the GL of the 10 Jan receipt and 25 Jan delivery |
| Cost changes | 10 Jan +1,000; 21 Jan Milk consumed 5,800 -> 6,800; Milk Powder 580 -> 680/kg; 25 Jan COGS 5,800 -> 6,800 |
| Unchanged | opening, all quantities, 15 Jan cost, 20 Jan receipt value, both closing balances |
| Recalculation | replay FIFO from the queue stored before 10 Jan; revalue the finished good from the new consumption; rebuild GL of vouchers whose value moved |
| Design | one heap in posting order, at most one valuation per entry, stop when the queue matches, push the finished good when a raw material moves |
| Running-balance problems | write amplification, locks, stale window, partial failure, closed periods, ordering drift, row size |

## Key Notes

- A submitted Purchase Receipt's rate is not editable. Here cancel and amend fails on negative stock, so the change comes through a Landed Cost Voucher or a Purchase Invoice rate difference.
- The 15 Jan delivery's cost does not change under FIFO. Its row is still rewritten because its stored balance and queue change.
- Milk's queue converges on 21 Jan. Any Milk entry after that keeps its stored values.
- In this single-warehouse setup the Manufacture posts no GL. The ₹1,000 moves from Stock In Hand to COGS through the 10 Jan receipt and the 25 Jan delivery.

---

## ERPNext Mapping

| This repo | ERPNext v15.50.0 |
|---|---|
| `FIFOQueue.add_stock` / `remove_stock` | [`FIFOValuation.add_stock`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/valuation.py#L74), [`remove_stock`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/valuation.py#L98) |
| `StockLedgerEntry.sort_key` | [`get_stock_ledger_entries`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L1613) (order by `posting_datetime`, `creation`) |
| `StockLedger.previous_sle` | [`get_previous_sle_of_current_voucher`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L1548) |
| `repost()` | [`repost_future_sle`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L234), [`update_entries_after.build`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L604), [`process_sle`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L774), [`update_queue_values`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L1357) |
| pushing the finished good | [`get_dependent_entries_to_fix`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L675) |
| `Voucher.set_outgoing_value` | [`update_outgoing_rate_on_transaction`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L1164), [`update_rate_on_stock_entry`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L1183), [`update_rate_on_delivery_and_sales_return`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L1199) |
| `Manufacture.incoming_rate_for` | [`recalculate_amounts_in_stock_entry`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L1190), [`get_basic_rate_for_manufactured_item`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/doctype/stock_entry/stock_entry.py#L882) |
| `dependant_sle_voucher_detail_no`, `recalculate_rate` | [`get_sle_for_source_warehouse`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/doctype/stock_entry/stock_entry.py#L1381), [`get_sle_for_target_warehouse`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/doctype/stock_entry/stock_entry.py#L1442) |
| `StockLedger._validate_future_qty` | [`validate_negative_qty_in_future_sle`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/stock_ledger.py#L1967) |
| `StockLedger.adjust_incoming_rate` | [`adjust_incoming_rate_for_pr`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/doctype/purchase_receipt/purchase_receipt.py#L1110), [`enable_recalculate_rate_in_sles`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/doctype/purchase_receipt/purchase_receipt.py#L922) |
| `gl_entries()` | [`StockController.get_gl_entries`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/controllers/stock_controller.py#L498), [`merge_similar_entries`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/accounts/general_ledger.py#L235) |
| not modelled: the background queue | [`repost_future_sle_and_gle`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/controllers/stock_controller.py#L1308), [`create_item_wise_repost_entries`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/controllers/stock_controller.py#L1714), [`repost`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/stock/doctype/repost_item_valuation/repost_item_valuation.py#L258), [`repost_gle_for_stock_vouchers`](https://github.com/frappe/erpnext/blob/v15.50.0/erpnext/accounts/utils.py#L1403) |
