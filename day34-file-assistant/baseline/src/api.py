"""HTTP-слой демо-магазина: checkout считает итог через PriceCalculator."""
from pricing import LineItem, PriceCalculator
from promo import promo_discount

_calculator = PriceCalculator(tax_rate=0.20)


def checkout(order: dict) -> dict:
    """order = {"items": [{"name", "unit_price", "quantity"}], "discount_percent", "promo_code"}."""
    items = [LineItem(i['name'], int(i['unit_price']), int(i.get('quantity', 1)))
             for i in order.get('items', [])]
    percent = float(order.get('discount_percent', 0.0))
    promo = promo_discount(order.get('promo_code', ''), _calculator.subtotal(items))
    total = _calculator.total_price(items, percent) - promo
    return {'total': max(total, 0), 'promo_discount': promo, 'items_count': len(items)}
