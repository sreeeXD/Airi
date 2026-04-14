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
                      parse_schedule_reply, generate_schedule_confirmation)
import os
from dotenv import load_dotenv
 
load_dotenv()
 
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
 
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
 
pending_reminder = {"active": False, "level": 0}
 
 
# ── Commands ──────────────────────────────────────────────────────────────────
 
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey! I'm your hydration girlfriend 💧\n\n"
        "I'll remind you to drink water throughout the day and make sure you actually do it.\n\n"
        "Commands:\n"
        "/status — today's progress\n"
        "/drank — log a glass manually\n"
        "/lab — toggle lab mode (skips 11am)\n"
        "/busy HH:MM — mark yourself busy until that time\n"
        "/free HH:MM — set free-from time\n"
        "/holiday — skip all reminders today\n"
        "/streak — see your streak\n"
        "/snooze — give me 10 mins\n\n"
        "You can also just reply naturally to my morning message to update your schedule 💙"
    )
 
 
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = get_today_count()
    streak = get_streak()
    bar = "💧" * count + "○" * max(0, 8 - count)
    lab = "ON" if get_lab_mode() else "OFF"
 
    await update.message.reply_text(
        f"Today: {bar}\n"
        f"{count}/8 glasses\n\n"
        f"Streak: {streak} day(s) 🔥\n"
        f"Lab mode: {lab}"
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
    if not current:
        await update.message.reply_text("Lab mode ON 🔬 I'll skip the 11am reminder today.")
    else:
        await update.message.reply_text("Lab mode OFF. 11am reminder is back on!")
 
 
async def busy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /busy HH:MM (e.g. /busy 15:30)")
        return
    time_str = args[0]
    try:
        h, m = map(int, time_str.split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
        set_busy_until(f"{h:02d}:{m:02d}")
        await update.message.reply_text(f"Got it! I won't bug you until {h:02d}:{m:02d} 🤐")
    except Exception:
        await update.message.reply_text("Invalid time format. Use HH:MM like /busy 15:30")
 
 
async def free_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /free HH:MM (e.g. /free 16:00)")
        return
    time_str = args[0]
    try:
        h, m = map(int, time_str.split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
        set_free_from(f"{h:02d}:{m:02d}")
        await update.message.reply_text(f"Got it! I'll start reminders from {h:02d}:{m:02d} 💙")
    except Exception:
        await update.message.reply_text("Invalid time format. Use HH:MM like /free 16:00")
 
 
async def holiday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_skip_all(True)
    await update.message.reply_text(
        "Holiday mode ON 🎉 No reminders today!\n"
        "But please still drink water on your own okay? 🥺"
    )
 
 
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
 
 
async def snooze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not pending_reminder["active"]:
        await update.message.reply_text("No active reminder to snooze! But drink water anyway 💧")
        return
    await update.message.reply_text("Okay fine, 10 minutes 🙄 But I'm watching the clock...")
    pending_reminder["active"] = False
 
    async def reremind():
        await asyncio.sleep(600)
        pending_reminder["active"] = True
        pending_reminder["level"] = min(pending_reminder["level"] + 1, 2)
        await send_reminder(context.application, escalation_level=pending_reminder["level"])
 
    asyncio.create_task(reremind())
 
 
# ── Morning check-in ──────────────────────────────────────────────────────────
 
async def send_checkin(app):
    """Send the morning good morning + schedule check message"""
    if get_checkin_done():
        return
 
    streak = get_streak()
    message = await generate_good_morning(streak)
 
    keyboard = [[
        InlineKeyboardButton("Same as usual ✅", callback_data="checkin_default"),
        InlineKeyboardButton("Something changed", callback_data="checkin_changed"),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
 
    await app.bot.send_message(
        chat_id=CHAT_ID,
        text=message,
        reply_markup=reply_markup
    )
    set_checkin_done(True)
    logger.info("Morning check-in sent")
 
 
# ── Media handlers ────────────────────────────────────────────────────────────
 
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checking your proof... 🔍")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    verified = await verify_proof_image(bytes(file_bytes))
 
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
    """Handle free-text replies — mainly for schedule updates after morning check-in"""
    if not get_awaiting_checkin_reply():
        return  # not waiting for a schedule reply, ignore
 
    user_text = update.message.text
    await update.message.reply_text("Let me check that... 🤔")
 
    parsed = await parse_schedule_reply(user_text)
 
    # Apply parsed schedule changes
    if parsed.get("lab_today"):
        set_lab_mode(True)
    if parsed.get("busy_until"):
        set_busy_until(parsed["busy_until"])
    if parsed.get("free_from"):
        set_free_from(parsed["free_from"])
    if parsed.get("skip_all"):
        set_skip_all(True)
 
    set_awaiting_checkin_reply(False)
 
    confirmation = await generate_schedule_confirmation(parsed)
    await update.message.reply_text(confirmation)
 
 
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
        pending_reminder["active"] = False
 
        async def reremind():
            await asyncio.sleep(600)
            pending_reminder["active"] = True
            pending_reminder["level"] = min(pending_reminder["level"] + 1, 2)
            await send_reminder(context.application, escalation_level=pending_reminder["level"])
 
        asyncio.create_task(reremind())
 
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
            "You can say things like:\n"
            "• 'lab today'\n"
            "• 'busy till 3pm'\n"
            "• 'free only after 5'\n"
            "• 'holiday, no college'\n"
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
    reply_markup = InlineKeyboardMarkup(keyboard)
 
    await app.bot.send_message(
        chat_id=CHAT_ID,
        text=message,
        reply_markup=reply_markup
    )
 
    # Auto-escalate if ignored after 1 minute
    async def check_if_ignored():
        await asyncio.sleep(60)
        if pending_reminder["active"]:
            next_level = min(escalation_level + 1, 2)
            logger.info(f"Reminder ignored — escalating to level {next_level}")
            await send_reminder(app, escalation_level=next_level)
 
    asyncio.create_task(check_if_ignored())
 
 
# ── Main ──────────────────────────────────────────────────────────────────────
 
def main():
    init_db()
    from telegram.request import HTTPXRequest
    
    # PythonAnywhere fix: Force explicitly defined proxy server
    # Their bash consoles sometimes do not pass the http_proxy env var correctly to httpx
    is_pythonanywhere = os.environ.get("USER") == "sreeXD" or "PYTHONANYWHERE_DOMAIN" in os.environ
    if is_pythonanywhere:
        proxy = "http://proxy.server:3128"
        t_request = HTTPXRequest(http_version="1.1", connection_pool_size=8, proxy_url=proxy)
        app = Application.builder().token(BOT_TOKEN).request(t_request).build()
    else:
        app = Application.builder().token(BOT_TOKEN).build()
 
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("drank", drank_command))
    app.add_handler(CommandHandler("lab", lab_command))
    app.add_handler(CommandHandler("busy", busy_command))
    app.add_handler(CommandHandler("free", free_command))
    app.add_handler(CommandHandler("holiday", holiday_command))
    app.add_handler(CommandHandler("streak", streak_command))
    app.add_handler(CommandHandler("snooze", snooze_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
 
    start_scheduler(app, send_reminder, send_checkin)
 
    logger.info("Hydration bot started — Phase 2!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
 
 
if __name__ == "__main__":
    main()
 