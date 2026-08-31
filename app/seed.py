from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Child, Parent, Subject, Subscription

MOCK_DATA = [
    ("Иванова Мария", "Алиса Иванова", "7L1-4827", [("Математика", 2500), ("Английский", 3000)]),
    ("Петров Иван", "Тимур Петров", "7L1-1593", [("Математика", 2500)]),
    ("Сидорова Анна", "Мария Сидорова", "7L1-7316", [("Английский", 3000)]),
]


async def seed_mock_data(session: AsyncSession) -> bool:
    if await session.scalar(select(func.count()).select_from(Parent)):
        return False
    subjects: dict[str, Subject] = {}
    for parent_name, child_name, code, items in MOCK_DATA:
        parent = Parent(full_name=parent_name, link_code=code)
        child = Child(full_name=child_name, parent=parent)
        session.add(parent)
        for subject_name, amount in items:
            subject = subjects.setdefault(subject_name, Subject(name=subject_name))
            child.subscriptions.append(Subscription(subject=subject, monthly_amount=amount))
    await session.commit()
    return True
