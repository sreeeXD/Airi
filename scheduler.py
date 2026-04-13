import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from db import get_lab_mode, reset_daily_if_needed, update_streak
import pytz

logger = logging.getLogger(__name__)

# Your timezone — change if needed
TIMEZONE = pytz.timezone("Asia/Kolkata")


def start_scheduler(app, send_reminder_fn):
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # --- Your daily reminder slots ---
    # Format: (hour, minute, label, escalation_level_if_ignored)

    reminders = [
        (7, 15, "morning"),        # wake up
        (9, 45, "college_start"),  # settled into college
        (11, 5, "short_break"),    # 11am break (skipped on lab days)
        (12, 15, "lunch"),         # lunch
        (14, 30, "afternoon"),     # mid afternoon
        (16, 0, "post_college"),   # just got home
        (18, 30, "evening"),       # evening
        (21, 30, "night"),         # night
    ]

    for hour, minute, label, *_ in reminders:
        async def make_job(h=hour, m=minute, lbl=label):
            async def job():
                # Skip 11am reminder if lab mode is on
                if lbl == "short_break" and get_lab_mode():
                    logger.info("Lab mode on — skipping 11am reminder")
                    return
                reset_daily_if_needed()
                await send_reminder_fn(app, escalation_level=0)
            return job

        import asyncio

        # We need a sync wrapper for APScheduler
        def make_sync_job(h=hour, m=minute, lbl=label):
            async def async_job():
                if lbl == "short_break" and get_lab_mode():
                    logger.info("Lab mode on — skipping 11am reminder")
                    return
                reset_daily_if_needed()
                await send_reminder_fn(app, escalation_level=0)

            def sync_job():
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(async_job())
                    else:
                        loop.run_until_complete(async_job())
                except RuntimeError:
                    asyncio.run(async_job())

            return sync_job

        scheduler.add_job(
            make_sync_job(hour, minute, label),
            CronTrigger(hour=hour, minute=minute, timezone=TIMEZONE),
            id=f"reminder_{label}",
            replace_existing=True
        )
        logger.info(f"Scheduled reminder: {label} at {hour:02d}:{minute:02d} IST")

    # Midnight job: update streak, reset lab mode
    def midnight_reset():
        update_streak()
        from db import set_lab_mode
        set_lab_mode(False)
        logger.info("Midnight reset done — streak updated, lab mode cleared")

    scheduler.add_job(
        midnight_reset,
        CronTrigger(hour=0, minute=1, timezone=TIMEZONE),
        id="midnight_reset",
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started with IST timezone")
    return scheduler
