from pathlib import Path

import pytest

from app.storage import LocalReceiptStorage


async def test_receipt_storage(tmp_path: Path):
    storage = LocalReceiptStorage(tmp_path)
    result = await storage.save(
        b"receipt",
        month="2026-09",
        parent_name="Иванова Мария",
        child_name="Алиса Иванова",
        amount=5500,
        suffix=".jpg",
    )
    assert result.key.startswith("2026/09/")
    assert storage.path(result.key).read_bytes() == b"receipt"
    with pytest.raises(ValueError):
        storage.path("../secret")
