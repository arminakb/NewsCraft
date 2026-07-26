from __future__ import annotations

import asyncio
from pathlib import Path

from app.db.session import async_session
from qualification.content_intelligence_report import DEFAULT_REPORT_PATH, generate_content_intelligence_report


async def main() -> None:
    output_path = _repo_root() / DEFAULT_REPORT_PATH
    async with async_session() as session:
        written = await generate_content_intelligence_report(session, output_path)
    print(written)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    asyncio.run(main())
