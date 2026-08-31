from __future__ import annotations

from decimal import Decimal

MONTHS = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}


def month_name(value: str) -> str:
    return MONTHS[int(value.split("-")[1])]


def money(value: Decimal | int) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₽"
