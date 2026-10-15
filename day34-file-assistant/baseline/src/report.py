"""Текстовый отчёт по корзине для бухгалтерии."""
from pricing import PriceCalculator


def render_report(title: str, cart) -> str:
    calc: PriceCalculator = cart.calculator
    lines = [f'# {title}', '']
    for item in cart.items:
        lines.append(f'- {item.name}: {item.quantity} x {item.unit_price} = {item.subtotal()}')
    lines.append('')
    lines.append(f'Подытог: {calc.subtotal(cart.items)}')
    lines.append(f'Итого с налогом: {calc.total_price(cart.items)}')
    return '\n'.join(lines)
