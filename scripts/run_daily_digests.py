"""Daily digest generator. Run from cron at ~04:00 UTC.

For every child where ai_digests_enabled is True, generate a 24h digest and
persist it. Logs progress; never crashes the cron line.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

from sqlalchemy import select

from app.ai_digest import generate_and_persist
from app.database import SessionLocal, init_db
from app.models import Child


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("daily-digests")
    init_db()

    with SessionLocal() as db:
        children = db.execute(
            select(Child).where(Child.ai_digests_enabled.is_(True))
        ).scalars().all()
        log.info("opted-in children: %d", len(children))
        for c in children:
            try:
                row = generate_and_persist(db, c, hours=24, period_label="daily")
                log.info(
                    "child=%s digest=%s tokens_in=%d tokens_out=%d cost=$%.4f%s",
                    c.id, row.id, row.input_tokens, row.output_tokens, row.cost_usd,
                    f" error={row.error}" if row.error else "",
                )
            except Exception as e:
                log.exception("digest failed for child %s: %s", c.id, e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
