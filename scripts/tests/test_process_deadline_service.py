"""Testes das funções puras do process_deadline_service. Não acessa o banco."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.process_deadline_service import (
    add_business_days,
    suggest_deadline_from_disponibilizacao,
)


def main():
    # sexta 2026-07-17 + 1 dia útil = segunda 2026-07-20
    assert add_business_days(date(2026, 7, 17), 1) == date(2026, 7, 20)
    # segunda + 5 dias úteis = segunda seguinte
    assert add_business_days(date(2026, 7, 20), 5) == date(2026, 7, 27)
    # sábado + 1 dia útil = segunda
    assert add_business_days(date(2026, 7, 18), 1) == date(2026, 7, 20)

    # Disponibilização quarta 2026-07-22 → publicação quinta 23 → +15 úteis = 2026-08-13
    assert suggest_deadline_from_disponibilizacao(date(2026, 7, 22)) == date(2026, 8, 13)
    # Disponibilização sexta 2026-07-24 → publicação segunda 27 → +15 úteis = 2026-08-17
    assert suggest_deadline_from_disponibilizacao(date(2026, 7, 24)) == date(2026, 8, 17)

    print('[OK] Todos os testes do process_deadline_service passaram.')


if __name__ == '__main__':
    main()
