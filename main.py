import asyncio
from bot.scheduler import start_scheduler

async def main():
    print("Запуск бота...")
    await start_scheduler()
    while True:
        await asyncio.sleep(3600)  # Бесконечное ожидание

if __name__ == "__main__":
    asyncio.run(main())
