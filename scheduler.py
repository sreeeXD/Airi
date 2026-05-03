import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from db import should_send_reminder, reset_daily_if_needed, update_streak, midnight_reset_settings
import pytz

logger = logging.getLogger(__name__)
TIMEZONE = pytz.timezone("Asia/Kolkata")

REMINDERS = [
    (7,  15, "morning",       "*"),
    (9,  45, "clg_start",     "0-5"),
    (11,  5, "break",         "0,2,5"),   # Mon/Wed/Sat only
    (12, 20, "lunch",         "0-5"),
    (14, 30, "afternoon",     "0-5"),
    (16, 10, "post_clg",      "0-5"),
    # Evening — every 30 mins
    (16, 30, "eve_1",  "*"),
    (17,  0, "eve_2",  "*"),
    (17, 30, "eve_3",  "*"),
    (18,  0, "eve_4",  "*"),
    (18, 30, "eve_5",  "*"),
    (19,  0, "eve_6",  "*"),
    (20,  0, "eve_7",  "*"),
    (20, 30, "eve_8",  "*"),
    (21,  0, "eve_9",  "*"),
    (21, 30, "night",  "*"),
]


def start_scheduler(app, send_reminder_fn, send_checkin_fn):
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    for hour, minute, label, dow in REMINDERS:
        def make_job(h=hour, m=minute, lbl=label):
            async def job():
                if not should_send_reminder(h, m):
                    logger.info(f"Skipping {lbl}")
                    return
                reset_daily_if_needed()
                await send_reminder_fn(app, escalation_level=0)
            return job

        scheduler.add_job(
            make_job(hour, minute, label),
            CronTrigger(hour=hour, minute=minute, day_of_week=dow, timezone=TIMEZONE),
            id=f"reminder_{label}", replace_existing=True
        )

    async def checkin_job():
        await send_checkin_fn(app)

    scheduler.add_job(checkin_job, CronTrigger(hour=7, minute=5, timezone=TIMEZONE),
                      id="morning_checkin", replace_existing=True)

    async def midnight():
        update_streak()
        midnight_reset_settings()

    scheduler.add_job(midnight, CronTrigger(hour=0, minute=1, timezone=TIMEZONE),
                      id="midnight_reset", replace_existing=True)

    scheduler.start()
    logger.info("Scheduler started — 18 reminders/day")
    return scheduler