from __future__ import annotations

from typing import Protocol


class SheetsExporter(Protocol):
    async def export_parents(self, rows: list[dict[str, object]]) -> None: ...
    async def export_payments(self, rows: list[dict[str, object]]) -> None: ...


class DisabledSheetsExporter:
    """MVP no-op adapter; replace without changing the application service layer."""

    async def export_parents(self, rows: list[dict[str, object]]) -> None:
        return None

    async def export_payments(self, rows: list[dict[str, object]]) -> None:
        return None
