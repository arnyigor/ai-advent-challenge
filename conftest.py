"""Root pytest bootstrap.

Делает корень репозитория импортируемым для тестов, чтобы работали импорты
вида `from tools.llm... import ...` независимо от того, откуда запущен pytest.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Модули дней лежат в подпапках dayNN-*; для тестов добавляем папку дня.
DAY03 = ROOT / "day03-reasoning-modes"
if str(DAY03) not in sys.path:
    sys.path.insert(0, str(DAY03))

DAY04 = ROOT / "day04-temperature"
if str(DAY04) not in sys.path:
    sys.path.insert(0, str(DAY04))

DAY05 = ROOT / "day05-model-versions"
if str(DAY05) not in sys.path:
    # В Day 4 и Day 5 есть модуль experiment.py. Day 4 исторически импортирует
    # его как top-level `experiment`, поэтому Day 5 добавляем в конец и в его
    # тестах загружаем experiment по уникальному имени.
    sys.path.append(str(DAY05))
