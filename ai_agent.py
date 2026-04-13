import os
import base64
import logging
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Use flash for speed and free tier compatibility
TEXT_MODEL = "gemini-1.5-flash"
VISION_MODEL = "gemini-1.5-flash"

# Girlfriend persona prompt
PERSONA = """You are a caring, slightly dramatic girlfriend who is VERY concerned about her boyfriend's water intake 
because he almost got kidney stones before. You genuinely care about his health.

Your personality:
- Sweet and caring at level 0 (first reminder)
- A little dramatic and worried at level 1 (ignored once)
- Full panic/guilt mode at level 2 (ignored twice — bring up the kidney stones!)

Keep messages SHORT (2-3 sentences max). Use casual language. 
Use emojis naturally but don't overdo it. Sound like a real girlfriend texting, not a bot.
Never use hashtags. Never sound corporate."""


async def generate_reminder(escalation_level: int, drinks_today: int) -> str:
    try:
        model = genai.GenerativeModel(TEXT_MODEL)

        level_context = {
            0: "Send a sweet first reminder. Be gentle and loving.",
            1: "He ignored the last reminder. Be a bit more persistent and slightly dramatic. Show you're a little worried.",
            2: "He's ignored multiple reminders. FULL girlfriend panic mode. Mention the kidney stones. Guilt trip him lovingly. Be dramatic but caring."
        }

        prompt = f"""{PERSONA}

Current situation:
- He's had {drinks_today} glasses of water today (goal is 8)
- This is escalation level {escalation_level}: {level_context.get(escalation_level, level_context[2])}

Write ONE reminder message to send him on Telegram right now."""

        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        logger.error(f"Gemini text error: {e}")
        # Fallback messages if API fails
        fallbacks = [
            "Hey! Don't forget to drink water 💧",
            "Babe... water. Now. Please 🥺",
            "DRINK WATER RIGHT NOW I'm not joking 😤💧"
        ]
        return fallbacks[min(escalation_level, 2)]


async def generate_verification_response(verified: bool, drink_count: int) -> str:
    try:
        model = genai.GenerativeModel(TEXT_MODEL)

        if verified:
            prompt = f"""{PERSONA}

He just sent proof that he drank water! React happily and encouragingly.
He's had {drink_count} glasses today out of 8.
{'He hit his daily goal!' if drink_count >= 8 else f'He still needs {8 - drink_count} more glasses today.'}
Keep it short and sweet."""
        else:
            prompt = f"""{PERSONA}

He sent a photo as proof he drank water, but it doesn't clearly show him drinking.
Playfully call him out and ask for better proof. Be funny but firm.
Keep it short."""

        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        logger.error(f"Gemini verification response error: {e}")
        if verified:
            return f"Yay!! That's {drink_count}/8 today 💙"
        else:
            return "Hmm I can't tell if you actually drank 🤨 Send a clearer photo!"


async def verify_proof_image(image_bytes: bytes) -> bool:
    """Use Gemini Vision to verify the user is actually drinking water"""
    try:
        model = genai.GenerativeModel(VISION_MODEL)

        image_data = {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(image_bytes).decode("utf-8")
        }

        prompt = """Look at this image carefully. 

Does this image show any of the following:
- A person drinking water or any liquid
- A glass/bottle of water being held or recently used
- An empty glass that was clearly just used
- Someone clearly about to drink water

Answer with ONLY "YES" or "NO". 
Be reasonably lenient — if there's a water bottle or glass present and it looks like they've been drinking, say YES.
Only say NO if there's clearly no drinking-related content at all."""

        response = model.generate_content([prompt, image_data])
        answer = response.text.strip().upper()
        logger.info(f"Vision verification result: {answer}")
        return "YES" in answer

    except Exception as e:
        logger.error(f"Gemini vision error: {e}")
        # If vision fails, give benefit of the doubt
        return True
