# Прайсинг корзины (demo-shop)

Мини-пакет для расчёта стоимости корзины: позиции, скидка в процентах, налог.

## Структура

- `src/pricing.py` — класс `PriceCalculator`, вся математика цен.
- `src/cart.py` — корзина, хранит позиции.
- `src/api.py` — HTTP-слой checkout.
- `src/report.py` — текстовый отчёт.

## Использование

```python
from pricing import LineItem, PriceCalculator

calc = PriceCalculator()
items = [LineItem('хлеб', 5000, 2)]
print(calc.total(items))  # FIXME: устаревший пример, см. pricing.py
```

## Возможности

- Скидка в процентах на всю корзину.
- Налог 20% по умолчанию.
- Промокоды не поддерживаются.

## Тесты

```powershell
python -m pytest tests/
```
