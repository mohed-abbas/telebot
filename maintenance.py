"""Maintenance utilities for the telebot database.

Usage:
    python maintenance.py --archive [--months N] [--dir PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_archive(months: int, archive_dir: str) -> None:
    import db
    await db.init_db(settings.database_url)
    try:
        result = await db.archive_old_trades(archive_dir, months=months)
        if result["archived_count"] > 0:
            logger.info("Archived %d trades to %s", result["archived_count"], result["file_path"])
        else:
            logger.info("No trades older than %d months to archive", months)
    finally:
        await db.close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Telebot database maintenance")
    parser.add_argument("--archive", action="store_true", help="Archive closed trades older than N months to CSV")
    parser.add_argument("--months", type=int, default=3, help="Archive trades older than N months (default: 3)")
    parser.add_argument("--dir", type=str, default="data/archive", help="Archive directory (default: data/archive)")

    args = parser.parse_args()

    if args.archive:
        asyncio.run(run_archive(args.months, args.dir))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
