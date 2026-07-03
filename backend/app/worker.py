import argparse
import asyncio

from app.db.session import async_session
from app.ingestion.service import IngestionService


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", action="append", choices=["rss", "atom", "telegram_public"])
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args()

    async with async_session() as session:
        service = IngestionService(session)
        stats = await service.run_once(platforms=args.platform, trigger=args.trigger)
        print(stats)


if __name__ == "__main__":
    asyncio.run(main())
