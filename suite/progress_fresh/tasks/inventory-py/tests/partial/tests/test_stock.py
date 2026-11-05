from inventory import stock


def test_low_stock_below():
    assert stock.low_stock({"a": 1, "b": 9}, 5) == ["a"]


def test_low_stock_above():
    assert stock.low_stock({"a": 10}, 5) == []


def test_low_stock_at():
    assert stock.low_stock({"a": 5}, 5) == ["a"]
