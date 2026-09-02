"""Root pytest bootstrap.

Делает корень репозитория импортируемым для тестов, чтобы работали импорты
вида `from tools.llm... import ...` независимо от того, откуда запущен pytest.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
