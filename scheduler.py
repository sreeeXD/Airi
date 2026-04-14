import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from db import should_send_reminder, reset_daily_if_needed, update_streak, midnight_reset_settings
import pytz
 
logger = logging.getLogger(__name__)
 
TIMEZONE = pytz.timezone("Asia/Kolkata")
 
REMINDERS = [
    (7,  15, "morning"),
    (9,  45, "college_start"),
    (11,  5, "short_break"),
    (12, 15, "lunch"),
    (14, 30, "afternoon"),
    (16,  0, "post_college"),
    (18, 30, "evening"),
    (21, 30, "night"),
]
 
 
def start_scheduler(app, send_reminder_fn, send_checkin_fn):
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
 
    for hour, minute, label in REMINDERS:
        def make_job(h=hour, m=minute, lbl=label):
            async def job():
                if not should_send_reminder(h, m):
                    logger.info(f"Skipping reminder: {lbl} at {h:02d}:{m:02d}")
                    return
                reset_daily_if_needed()
                await send_reminder_fn(app, escalation_level=0)
            return job
 
        scheduler.add_job(
            make_job(hour, minute, label),
            CronTrigger(hour=hour, minute=minute, timezone=TIMEZONE),
            id=f"reminder_{label}",
            replace_existing=True
        )
        logger.info(f"Scheduled: {label} at {hour:02d}:{minute:02d} IST")
 
    # Morning check-in at 7:05 AM (before first reminder at 7:15)
    async def morning_checkin_job():
        await send_checkin_fn(app)
 
    scheduler.add_job(
        morning_checkin_job,
        CronTrigger(hour=7, minute=5, timezone=TIMEZONE),
        id="morning_checkin",
        replace_existing=True
    )
    logger.info("Scheduled: morning check-in at 07:05 IST")
 
    # Midnight reset
    async def midnight_reset():
        update_streak()
        midnight_reset_settings()
        logger.info("Midnight reset done — streak updated, schedule cleared")
 
    scheduler.add_job(
        midnight_reset,
        CronTrigger(hour=0, minute=1, timezone=TIMEZONE),
        id="midnight_reset",
        replace_existing=True
    )
 
    scheduler.start()
    logger.info("Scheduler started — IST timezone")
    return scheduler
 