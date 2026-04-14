import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from scheduler import start_scheduler
from db import init_db, log_drink, get_today_count, get_streak, set_lab_mode, get_lab_mode
from ai_agent import generate_reminder, generate_verification_response, verify_proof_image
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
 
# Global state for pending reminders
pending_reminder = {"active": False, "level": 0, "job": None}
 
 
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey! I'm your hydration girlfriend 💧\n\n"
        "I'll remind you to drink water throughout the day and make sure you actually do it.\n\n"
        "Commands:\n"
        "/status — see today's progress\n"
        "/drank — log a glass manually\n"
        "/lab — toggle lab mode (skips 11am reminder)\n"
        "/streak — see your streak\n"
        "/snooze — give me 10 mins\n\n"
        "Stay hydrated babe 💙"
    )
 
 
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = get_today_count()
    streak = get_streak()
    goal = 8
    bar = "💧" * count + "○" * max(0, goal - count)
    lab = "ON (11am skipped)" if get_lab_mode() else "OFF"
 
    await update.message.reply_text(
        f"Today's hydration: {bar}\n"
        f"{count}/{goal} glasses\n\n"
        f"Streak: {streak} day(s) 🔥\n"
        f"Lab mode: {lab}"
    )
 
 
async def drank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_drink()
    count = get_today_count()
    pending_reminder["active"] = False
    pending_reminder["level"] = 0
 
    responses = [
        "Yay!! Good job babe 💙 That's glass number {}!",
        "FINALLY 😤 but also... proud of you 💙 #{} done!",
        "There you go!! #{} glass down, keep it up 💪",
        "Okay okay I'll stop nagging... for now 😏 #{} done!",
    ]
    import random
    msg = random.choice(responses).format(count)
 
    if count >= 8:
        msg += "\n\n🎉 You hit your daily goal!! I'm actually so proud of you right now."
 
    await update.message.reply_text(msg)
 
 
async def lab_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = get_lab_mode()
    set_lab_mode(not current)
    if not current:
        await update.message.reply_text("Lab mode ON 🔬 I'll skip the 11am reminder today.")
    else:
        await update.message.reply_text("Lab mode OFF. 11am reminder is back on!")
 
 
async def streak_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    streak = get_streak()
    if streak == 0:
        await update.message.reply_text("No streak yet 😢 Let's start today!")
    elif streak < 3:
        await update.message.reply_text(f"Streak: {streak} day(s) 🌱 Good start, keep going!")
    elif streak < 7:
        await update.message.reply_text(f"Streak: {streak} days 🔥 You're doing great!")
    else:
        await update.message.reply_text(f"Streak: {streak} days 🏆 Okay this is actually impressive, I'm proud of you!!")
 
 
async def snooze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not pending_reminder["active"]:
        await update.message.reply_text("No active reminder to snooze! But drink water anyway 💧")
        return
 
    await update.message.reply_text(
        "Okay fine, 10 minutes 🙄 But I'm watching the clock..."
    )
    pending_reminder["active"] = False
 
    # Re-trigger after 10 minutes
    async def reremind():
        await asyncio.sleep(600)
        pending_reminder["active"] = True
        pending_reminder["level"] = min(pending_reminder["level"] + 1, 2)
        await send_reminder(context.application, escalation_level=pending_reminder["level"])
 
    asyncio.create_task(reremind())
 
 
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle proof photos sent by user"""
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
 
 
async def send_reminder(app, escalation_level=0):
    """Send a reminder message with inline buttons, then auto-escalate if ignored"""
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
 
    # Auto-escalate if ignored — check after 15 mins
    async def check_if_ignored():
        await asyncio.sleep(60)  # 1 minute
        if pending_reminder["active"]:  # still not responded
            next_level = min(escalation_level + 1, 2)
            logger.info(f"Reminder ignored! Auto-escalating to level {next_level}")
            await send_reminder(app, escalation_level=next_level)
 
    asyncio.create_task(check_if_ignored())
 
 
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
 
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("drank", drank_command))
    app.add_handler(CommandHandler("lab", lab_command))
    app.add_handler(CommandHandler("streak", streak_command))
    app.add_handler(CommandHandler("snooze", snooze_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))
 
    # Start scheduler
    start_scheduler(app, send_reminder)
 
    logger.info("Hydration bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
 
 
if __name__ == "__main__":
    main()
 