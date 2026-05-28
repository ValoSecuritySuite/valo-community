"""Background scheduler for the Phase 4 Learning Loop refiner.

Mirrors :mod:`app.services.executive_aggregator`: a single asyncio task
that wakes up every ``settings.learning_loop_schedule_seconds``, runs
:func:`app.services.learning_loop.refiner.refine_once`, and goes back to
sleep. Cancellation is cooperative; the task swallows transient errors
so a single bad run does not crash the loop.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.logging import get_logger
from app.services.learning_loop.refiner import refine_once

logger = get_logger(__name__)


async def run_forever() -> None:
    """Run the refiner on a fixed cadence until cancelled."""
    interval = max(60, int(settings.learning_loop_schedule_seconds))
    logger.info("learning_loop_scheduler_started interval_seconds=%d", interval)
    try:
        while True:
            try:
                proposals = await asyncio.to_thread(refine_once)
                logger.info(
                    "learning_loop_cycle_completed proposals=%d", len(proposals)
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("learning_loop_cycle_failed")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("learning_loop_scheduler_stopped")
        raise


__all__ = ["run_forever"]
