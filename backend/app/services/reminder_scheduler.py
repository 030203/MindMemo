from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.notification_service import reminder_notification_service
from app.services.reminder_service import reminder_service
from app.services.review_service import review_service

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="mindmemo-reminder-scheduler")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("Reminder scheduler scan failed")
            await asyncio.sleep(max(settings.reminder_scan_interval_seconds, 15))

    def run_once(self) -> int:
        with SessionLocal() as db:
            created = reminder_service.sync_all_users(db)
            review_created = review_service.sync_all_users(db)
            sent = reminder_notification_service.dispatch_pending(db)
            if created > 0:
                logger.info("Reminder scheduler created %s reminder event(s)", created)
            if review_created > 0:
                logger.info("Reminder scheduler created %s review queue item(s)", review_created)
            if sent > 0:
                logger.info("Reminder scheduler sent %s reminder notification(s)", sent)
            return created


reminder_scheduler = ReminderScheduler()
