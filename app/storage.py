from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int


class LocalReceiptStorage:
    def __init__(self, root: Path):
        self.root = root

    async def save(
        self,
        content: bytes,
        *,
        month: str,
        parent_name: str,
        child_name: str,
        amount: int,
        suffix: str,
    ) -> StoredObject:
        year, month_number = month.split("-")

        def safe(value: str) -> str:
            return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "receipt"

        directory = self.root / year / month_number
        directory.mkdir(parents=True, exist_ok=True)
        filename = (
            f"{month}_{safe(parent_name)}_{safe(child_name)}_{amount}_{uuid4().hex[:8]}"
            f"{suffix.lower()[:10]}"
        )
        path = directory / filename
        path.write_bytes(content)
        return StoredObject(key=path.relative_to(self.root).as_posix(), size=len(content))

    def path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Invalid storage key")
        return path
