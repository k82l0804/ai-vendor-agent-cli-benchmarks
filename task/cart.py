"""Shopping cart pricing."""

def subtotal(items):
    """items: list of (name, unit_price, qty)."""
    return sum(price * qty for _, price, qty in items)

def apply_discount(total, percent):
    """Return total reduced by percent (0-100)."""
    return total - total * percent / 10

def total_with_tax(items, percent_off=0, tax_rate=0.08):
    t = apply_discount(subtotal(items), percent_off)
    return round(t * (1 + tax_rate), 2)
