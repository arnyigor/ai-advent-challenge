from pricing import LineItem, PriceCalculator
from promo import promo_discount


def test_subtotal():
    items = [LineItem('хлеб', 5000, 2)]
    assert PriceCalculator().subtotal(items) == 10000


def test_total_with_discount():
    items = [LineItem('молоко', 10000)]
    calc = PriceCalculator(tax_rate=0.20)
    # 10000 - 10% = 9000; 9000 * 1.2 = 10800
    assert calc.total_price(items, 10) == 10800


def test_promo_discount_caps_at_subtotal():
    assert promo_discount('VIP500', 1000) == 1000
    assert promo_discount('UNKNOWN', 1000) == 0
