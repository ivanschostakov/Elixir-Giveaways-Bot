from logger import setup_logging

from src.bot import run_bot
from src.integrations.bitrix24 import bitrix24


async def main():
    await bitrix24.open()
    await run_bot()
    await bitrix24.close()

if __name__ == "__main__":
    setup_logging()

    import asyncio
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
