from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Base


async def clear_all_data(session: AsyncSession) -> dict[str, int]:
    deleted_by_table: dict[str, int] = {}

    # Delete in reverse dependency order to satisfy FK constraints.
    for table in reversed(Base.metadata.sorted_tables):
        result = await session.execute(delete(table))
        rowcount = result.rowcount if (result.rowcount and result.rowcount > 0) else 0
        deleted_by_table[table.name] = rowcount

    await session.commit()
    return deleted_by_table
