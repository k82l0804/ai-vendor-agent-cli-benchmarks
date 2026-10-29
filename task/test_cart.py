from cart import subtotal, apply_discount, total_with_tax

def test_subtotal():
    assert subtotal([("a", 2.0, 3), ("b", 1.5, 2)]) == 9.0

def test_discount():
    assert apply_discount(200.0, 10) == 180.0

def test_total():
    assert total_with_tax([("a", 100.0, 1)], percent_off=10, tax_rate=0.1) == 99.0
