"""Промокоды: фиксированная скидка по коду. Новая фича, в CHANGELOG не внесена."""

PROMO_CODES = {
    'WELCOME10': 1000,  # 1000 копеек = 10 рублей
    'VIP500': 50000,
}


def promo_discount(code: str, subtotal: int) -> int:
    """Скидка по промокоду в копейках; не больше subtotal. Неизвестный код -> 0."""
    if not isinstance(code, str):
        return 0
    amount = PROMO_CODES.get(code.strip().upper(), 0)
    return min(amount, max(subtotal, 0))


def apply_promo(calculator, items, code: str) -> int:
    """Итог с промокодом: subtotal - промо + налог через PriceCalculator."""
    base = calculator.subtotal(items) - promo_discount(code, calculator.subtotal(items))
    return base + round(base * calculator.tax_rate)
