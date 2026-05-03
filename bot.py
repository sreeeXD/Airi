import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                           CallbackQueryHandler, filters, ContextTypes)
from scheduler import start_scheduler
from db import (init_db, log_drink, get_today_count, get_streak,
                set_lab_mode, get_lab_mode, set_checkin_done, get_checkin_done,
                set_awaiting_checkin_reply, get_awaiting_checkin_reply,
                set_busy_until, set_free_from, set_skip_all, midnight_reset_settings)
from ai_agent import (generate_reminder, generate_verification_response,
                      verify_proof_image, generate_good_morning,
                      parse_schedule_reply, generate_schedule_confirmation,
                      detect_snooze_intent, generate_snooze_response)
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))

pending_reminder = {"active": False, "level": 0}
MAX_ESCALATION = 3  # Phase 3: panic mode at level 3


# ── Commands ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey! I'm your hydration girlfriend 💧\n\n"
        "Commands:\n"
        "/status — today's progress\n"
        "/drank — log a glass manually\n"
        "/lab — toggle lab mode (skips 11am)\n"
        "/busy HH:MM — busy until that time\n"
        "/free HH:MM — free from that time\n"
        "/holiday — skip all reminders today\n"
        "/streak — see your streak\n"
        "/snooze — give me 10 mins\n\n"
        "You can also just TEXT me naturally:\n"
        "• 'give me 5' → snooze 5 mins\n"
        "• 'done' → log a drink\n"
        "• Send a photo/video as proof 💙"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = get_today_count()
    streak = get_streak()
    bar = "💧" * count + "○" * max(0, 8 - count)
    await update.message.reply_text(
        f"Today: {bar}\n{count}/8 glasses\n\nStreak: {streak} day(s) 🔥\nLab mode: {'ON' if get_lab_mode() else 'OFF'}"
    )


async def drank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_drink()
    count = get_today_count()
    pending_reminder["active"] = False
    pending_reminder["level"] = 0
    import random
    responses = [
        "Yay!! Good job babe 💙 That's glass number {}!",
        "FINALLY 😤 but also... proud of you 💙 #{} done!",
        "There you go!! #{} down, keep it up 💪",
        "Okay okay I'll stop nagging... for now 😏 #{} done!",
    ]
    msg = random.choice(responses).format(count)
    if count >= 8:
        msg += "\n\n🎉 You hit your daily goal!! I'm so proud of you!"
    await update.message.reply_text(msg)


async def lab_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = get_lab_mode()
    set_lab_mode(not current)
    await update.message.reply_text(
        "Lab mode ON 🔬 I'll skip the 11am reminder today." if not current
        else "Lab mode OFF. 11am reminder is back on!"
    )


async def busy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /busy HH:MM")
        return
    try:
        h, m = map(int, args[0].split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
        set_busy_until(f"{h:02d}:{m:02d}")
        await update.message.reply_text(f"Got it! I won't bug you until {h:02d}:{m:02d} 🤐")
    except:
        await update.message.reply_text("Invalid time. Use HH:MM like /busy 15:30")


async def free_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /free HH:MM")
        return
    try:
        h, m = map(int, args[0].split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
        set_free_from(f"{h:02d}:{m:02d}")
        await update.message.reply_text(f"Got it! I'll start reminders from {h:02d}:{m:02d} 💙")
    except:
        await update.message.reply_text("Invalid time. Use HH:MM like /free 16:00")


async def holiday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_skip_all(True)
    await update.message.reply_text("Holiday mode ON 🎉 No reminders today!\nBut please drink water anyway okay? 🥺")


async def streak_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    streak = get_streak()
    if streak == 0:
        await update.message.reply_text("No streak yet 😢 Let's start today!")
    elif streak < 3:
        await update.message.reply_text(f"Streak: {streak} day(s) 🌱 Good start!")
    elif streak < 7:
        await update.message.reply_text(f"Streak: {streak} days 🔥 You're doing great!")
    else:
        await update.message.reply_text(f"Streak: {streak} days 🏆 This is actually impressive!!")


async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime
    import pytz
    TIMEZONE = pytz.timezone("Asia/Kolkata")
    now = datetime.now(TIMEZONE)
    now_mins = now.hour * 60 + now.minute
    weekday = now.weekday()

    REMINDERS = [
        (7, 15, "morning"),
        (9, 45, "college start"),
        (11, 5, "short break"),
        (12, 20, "lunch"),
        (14, 30, "afternoon"),
        (16, 10, "post college"),
        (18, 30, "evening"),
        (21, 30, "night"),
    ]

    from db import should_send_reminder
    next_reminder = None
    for hour, minute, label in REMINDERS:
        slot_mins = hour * 60 + minute
        if slot_mins > now_mins and should_send_reminder(hour, minute):
            next_reminder = (hour, minute, label)
            break

    if next_reminder:
        h, m, label = next_reminder
        # Calculate time remaining
        diff = (h * 60 + m) - now_mins
        hrs = diff // 60
        mins = diff % 60
        time_str = f"{h:02d}:{m:02d}"
        if hrs > 0:
            remaining = f"{hrs}h {mins}m"
        else:
            remaining = f"{mins} mins"
        await update.message.reply_text(
            f"Next reminder: {time_str} ({label}) ⏰\nThat's in {remaining}!"
        )
    else:
        await update.message.reply_text(
            "No more reminders today! 🌙\nGet some rest and drink water before bed 💧"
        )


async def snooze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not pending_reminder["active"]:
        await update.message.reply_text("No active reminder to snooze! But drink water anyway 💧")
        return
    await _do_snooze(context.application, 10)
    await update.message.reply_text("Okay fine, 10 minutes 🙄")


# ── Snooze helper ─────────────────────────────────────────────────────────────

async def _do_snooze(app, minutes: int):
    pending_reminder["active"] = False

    async def reremind():
        await asyncio.sleep(minutes * 60)
        pending_reminder["active"] = True
        pending_reminder["level"] = min(pending_reminder["level"] + 1, MAX_ESCALATION)
        await send_reminder(app, escalation_level=pending_reminder["level"])

    asyncio.create_task(reremind())


# ── Morning check-in ──────────────────────────────────────────────────────────

async def send_checkin(app):
    if get_checkin_done():
        return
    streak = get_streak()
    message = await generate_good_morning(streak)
    keyboard = [[
        InlineKeyboardButton("Same as usual ✅", callback_data="checkin_default"),
        InlineKeyboardButton("Something changed", callback_data="checkin_changed"),
    ]]
    await app.bot.send_message(chat_id=CHAT_ID, text=message,
                               reply_markup=InlineKeyboardMarkup(keyboard))
    set_checkin_done(True)


# ── Media handlers ────────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checking your proof... 🔍")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    verified = await verify_proof_image(bytes(file_bytes), "image/jpeg")
    if verified:
        log_drink()
        count = get_today_count()
        pending_reminder["active"] = False
        pending_reminder["level"] = 0
        response = await generate_verification_response(True, count)
    else:
        response = await generate_verification_response(False, 0)
    await update.message.reply_text(response)


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 3: Handle video proof"""
    await update.message.reply_text("Checking your video proof... 🎥🔍")
    video = update.message.video or update.message.video_note
    file = await context.bot.get_file(video.file_id)
    file_bytes = await file.download_as_bytearray()

    # Extract thumbnail frame for vision verification
    thumb = video.thumbnail if hasattr(video, 'thumbnail') and video.thumbnail else None
    if thumb:
        thumb_file = await context.bot.get_file(thumb.file_id)
        thumb_bytes = await thumb_file.download_as_bytearray()
        verified = await verify_proof_image(bytes(thumb_bytes), "image/jpeg")
    else:
        # If no thumbnail, give benefit of the doubt for videos
        verified = True

    if verified:
        log_drink()
        count = get_today_count()
        pending_reminder["active"] = False
        pending_reminder["level"] = 0
        response = await generate_verification_response(True, count)
    else:
        response = await generate_verification_response(False, 0)
    await update.message.reply_text(response)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phase 3: Natural language snooze + schedule replies"""
    user_text = update.message.text

    # If waiting for schedule reply, handle that first
    if get_awaiting_checkin_reply():
        await update.message.reply_text("Let me check that... 🤔")
        parsed = await parse_schedule_reply(user_text)
        if parsed.get("lab_today"): set_lab_mode(True)
        if parsed.get("busy_until"): set_busy_until(parsed["busy_until"])
        if parsed.get("free_from"): set_free_from(parsed["free_from"])
        if parsed.get("skip_all"): set_skip_all(True)
        set_awaiting_checkin_reply(False)
        confirmation = await generate_schedule_confirmation(parsed)
        await update.message.reply_text(confirmation)
        return

    # Phase 3: detect snooze or drank intent from any message
    if pending_reminder["active"]:
        intent = await detect_snooze_intent(user_text)

        if intent.get("is_drank"):
            log_drink()
            count = get_today_count()
            pending_reminder["active"] = False
            pending_reminder["level"] = 0
            response = await generate_verification_response(True, count)
            await update.message.reply_text(response)
            return

        if intent.get("is_snooze"):
            minutes = intent.get("minutes", 10)
            await _do_snooze(context.application, minutes)
            response = await generate_snooze_response(minutes)
            await update.message.reply_text(response)
            return


# ── Inline button callbacks ───────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "drank":
        log_drink()
        count = get_today_count()
        pending_reminder["active"] = False
        pending_reminder["level"] = 0
        await query.edit_message_text(f"Logged! 💙 That's {count}/8 glasses today.")

    elif query.data == "snooze":
        await query.edit_message_text("Okay, 10 minutes... ⏰")
        await _do_snooze(context.application, 10)

    elif query.data == "skip":
        pending_reminder["active"] = False
        pending_reminder["level"] = 0
        await query.edit_message_text("Okay skipping this one 😒 But drink later okay?")

    elif query.data == "checkin_default":
        await query.edit_message_text("Perfect! Default schedule today 💙 I'll remind you as usual!")

    elif query.data == "checkin_changed":
        set_awaiting_checkin_reply(True)
        await query.edit_message_text(
            "Tell me what's different today! 📝\n\n"
            "e.g. 'lab today', 'busy till 3pm', 'holiday'"
        )


# ── Reminder sender ───────────────────────────────────────────────────────────

async def send_reminder(app, escalation_level=0):
    pending_reminder["active"] = True
    pending_reminder["level"] = escalation_level

    count = get_today_count()
    message = await generate_reminder(escalation_level, count)

    keyboard = [
        [
            InlineKeyboardButton("I drank! 💧", callback_data="drank"),
            InlineKeyboardButton("Snooze 10min ⏰", callback_data="snooze"),
        ],
        [InlineKeyboardButton("Skip this one", callback_data="skip")],
    ]

    await app.bot.send_message(chat_id=CHAT_ID, text=message,
                               reply_markup=InlineKeyboardMarkup(keyboard))

    # Auto-escalate after 1 min if ignored
    async def check_if_ignored():
        await asyncio.sleep(60)
        if pending_reminder["active"]:
            next_level = min(escalation_level + 1, MAX_ESCALATION)
            logger.info(f"Ignored — escalating to level {next_level}")
            await send_reminder(app, escalation_level=next_level)

    asyncio.create_task(check_if_ignored())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("drank", drank_command))
    app.add_handler(CommandHandler("lab", lab_command))
    app.add_handler(CommandHandler("busy", busy_command))
    app.add_handler(CommandHandler("free", free_command))
    app.add_handler(CommandHandler("holiday", holiday_command))
    app.add_handler(CommandHandler("streak", streak_command))
    app.add_handler(CommandHandler("next", next_command))
    app.add_handler(CommandHandler("snooze", snooze_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    start_scheduler(app, send_reminder, send_checkin)

    logger.info("Hydration bot started — Phase 3!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
# This will be inserted - see below