"""Корзина покупок: хранит позиции и считает итог через PriceCalculator."""
from pricing import LineItem, PriceCalculator


class Cart:
    def __init__(self, calculator: PriceCalculator | None = None):
        self.calculator = calculator or PriceCalculator()
        self.items: list[LineItem] = []

    def add(self, name: str, unit_price: int, quantity: int = 1) -> None:
        if unit_price < 0 or quantity < 1:
            raise ValueError('некорректная позиция')
        self.items.append(LineItem(name, unit_price, quantity))

    def total(self, discount_percent: float = 0.0) -> int:
        return self.calculator.total_price(self.items, discount_percent)
