from inventory import stock


def test_low_stock_below():
    assert stock.low_stock({"a": 1, "b": 9}, 5) == ["a"]
