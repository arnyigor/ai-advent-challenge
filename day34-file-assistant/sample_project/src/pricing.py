"""Расчёт стоимости корзины: позиции, скидка в процентах, налог."""
from dataclasses import dataclass


@dataclass(frozen=True)
class LineItem:
    """Позиция корзины: название, цена за единицу в копейках, количество."""
    name: str
    unit_price: int
    quantity: int = 1

    def subtotal(self) -> int:
        return self.unit_price * self.quantity


class PriceCalculator:
    """Считает сумму корзины со скидкой и налогом. Все суммы в копейках."""

    def __init__(self, tax_rate: float = 0.20):
        if not 0 <= tax_rate <= 1:
            raise ValueError('tax_rate должен быть в диапазоне 0..1')
        self.tax_rate = tax_rate

    def subtotal(self, items) -> int:
        return sum(item.subtotal() for item in items)

    def discount_amount(self, items, percent: float) -> int:
        if not 0 <= percent <= 100:
            raise ValueError('percent должен быть в диапазоне 0..100')
        return round(self.subtotal(items) * percent / 100)

    def total_price(self, items, discount_percent: float = 0.0) -> int:
        """Итоговая цена: subtotal - скидка + налог на облагаемую часть."""
        base = self.subtotal(items) - self.discount_amount(items, discount_percent)
        return base + round(base * self.tax_rate)
