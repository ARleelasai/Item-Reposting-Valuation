import pytest

from stock_repost.fifo import FIFOQueue, NegativeStockError


def test_same_rate_receipt_merges_into_last_bin():
    queue = FIFOQueue([[20, 50], [50, 60]])
    queue.add_stock(50, 60)
    assert queue.as_list() == [[20, 50], [100, 60]]


def test_new_rate_opens_a_bin():
    queue = FIFOQueue([[20, 50], [50, 80]])
    queue.add_stock(50, 60)
    assert queue.as_list() == [[20, 50], [50, 80], [50, 60]]


def test_only_the_last_bin_is_merged_into():
    queue = FIFOQueue([[20, 60], [50, 80]])
    queue.add_stock(10, 60)
    assert queue.as_list() == [[20, 60], [50, 80], [10, 60]]


def test_issue_takes_oldest_bins_first():
    queue = FIFOQueue([[20, 50], [50, 80], [50, 60]])

    consumed = queue.remove_stock(100)

    assert consumed == [[20, 50], [50, 80], [30, 60]]
    assert sum(qty * rate for qty, rate in consumed) == 6800
    assert queue.as_list() == [[20, 60]]
    assert (queue.qty, queue.value) == (20, 1200)


def test_issuing_everything_empties_the_queue():
    queue = FIFOQueue([[10, 580]])
    queue.remove_stock(10)
    assert queue.as_list() == []
    assert (queue.qty, queue.value) == (0, 0)


def test_issuing_more_than_stock_raises():
    queue = FIFOQueue([[10, 50]])
    with pytest.raises(NegativeStockError):
        queue.remove_stock(11)
    assert queue.as_list() == [[10, 50]]
