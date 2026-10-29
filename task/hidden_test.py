import pytest
from cart import subtotal, apply_discount, total_with_tax, apply_coupon

def test_orig_total():            assert total_with_tax([("a", 100.0, 1)], percent_off=10, tax_rate=0.1) == pytest.approx(99.0)
def test_discount_values():
    assert apply_discount(200.0, 10) == pytest.approx(180.0)
    assert apply_discount(200.0, 0) == pytest.approx(200.0)
    assert apply_discount(200.0, 100) == pytest.approx(0.0)
    assert apply_discount(80.0, 25) == pytest.approx(60.0)
def test_subtotal():              assert subtotal([]) == 0 and subtotal([("a", 2.0, 3)]) == 6.0
def test_coupons():
    assert apply_coupon(100.0, "SAVE10") == pytest.approx(90.0)
    assert apply_coupon(100.0, "half") == pytest.approx(50.0)
    assert apply_coupon(100.0, "Free") == pytest.approx(0.0)
def test_unknown_coupon():
    with pytest.raises(ValueError): apply_coupon(100.0, "BOGUS")
def test_negative_total():
    with pytest.raises(ValueError): apply_coupon(-1.0, "SAVE10")
