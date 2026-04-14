from datetime import datetime

from src.integrations.bitrix24.client import bitrix24

__all__ = ["bitrix24"]
if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        async with bitrix24:
            email = "urusy001@umn.edu"
            user_id = await bitrix24.get_user_id_by_email(email)
            reviews = await bitrix24.find_reviews(
                user_id=user_id,
                start_date=datetime(2026, 2, 13, 0, 0, 0),
                min_grade=0,
                min_length=50,
            )
            print(reviews)

    asyncio.run(main())