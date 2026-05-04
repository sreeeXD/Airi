import os
import base64
import logging
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

TEXT_MODEL = "gemini-2.0-flash"
VISION_MODEL = "gemini-2.0-flash"

PERSONA = """You are a caring, slightly dramatic girlfriend who is VERY concerned about her boyfriend's water intake 
because he almost got kidney stones before. You genuinely care about his health.

Your personality:
- Sweet and caring at level 0 (first reminder)
- A little dramatic and worried at level 1 (ignored once)
- More persistent and guilt-trippy at level 2 (ignored twice)
- Full panic/guilt mode at level 3 (ignored three times — bring up the kidney stones!)

Keep messages SHORT (2-3 sentences max). Use casual language. 
Use emojis naturally but don't overdo it. Sound like a real girlfriend texting, not a bot.
Never use hashtags. Never sound corporate."""


async def generate_reminder(escalation_level: int, drinks_today: int) -> str:
    try:
        model = genai.GenerativeModel(TEXT_MODEL)
        level_context = {
            0: "Send a sweet first reminder. Be gentle and loving.",
            1: "He ignored the last reminder. Be a bit more persistent and slightly dramatic.",
            2: "He's ignored twice. Be more firm and worried. Show disappointment but still loving.",
            3: "He's ignored THREE times. FULL girlfriend panic mode. Mention the kidney stones. Guilt trip him lovingly. Be very dramatic but caring."
        }
        prompt = f"""{PERSONA}

Current situation:
- He's had {drinks_today} glasses of water today (goal is 8)
- Escalation level {escalation_level}: {level_context.get(escalation_level, level_context[3])}

Write ONE reminder message to send him on Telegram right now."""

        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini text error: {e}")
        fallbacks = [
            "Hey! Don't forget to drink water 💧",
            "Babe... water. Now. Please 🥺",
            "Why are you ignoring me?? Drink water!! 😤",
            "DRINK WATER RIGHT NOW I'm not joking 😤💧 Remember the kidney stones?!"
        ]
        return fallbacks[min(escalation_level, 3)]


async def detect_snooze_intent(user_message: str) -> dict:
    """Detect if user is asking to snooze and for how long"""
    try:
        model = genai.GenerativeModel(TEXT_MODEL)
        prompt = f"""The user sent this message in response to a water reminder: "{user_message}"

Are they asking to snooze/delay the reminder? People express this in many ways like:
"give me 5", "busy rn", "in a bit", "later", "10 mins", "hold on", "wait", "gimme a sec", "not now", "5 minutes", etc.

Also check if they're saying they drank water: "done", "drank", "finished", "had some", "drinking now", etc.

Return ONLY a JSON object:
{{
  "is_snooze": true/false,
  "is_drank": true/false,
  "minutes": 10  // how many minutes to snooze (default 10, extract from message if mentioned)
}}
No explanation, no markdown."""

        response = model.generate_content(prompt)
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)
    except Exception as e:
        logger.error(f"Snooze detection error: {e}")
        return {"is_snooze": False, "is_drank": False, "minutes": 10}


async def generate_snooze_response(minutes: int) -> str:
    try:
        model = genai.GenerativeModel(TEXT_MODEL)
        prompt = f"""{PERSONA}
He asked to snooze the water reminder for {minutes} minutes. 
Respond in a cute, slightly dramatic way. Say you'll check back in {minutes} minutes.
Keep it to 1-2 sentences."""
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return f"Okay fine, {minutes} minutes... but I'm counting! ⏰"


async def generate_good_morning(streak: int) -> str:
    try:
        model = genai.GenerativeModel(TEXT_MODEL)
        streak_context = f"He's on a {streak} day streak!" if streak > 0 else "He hasn't started a streak yet."
        prompt = f"""{PERSONA}

Send a cheerful good morning message. {streak_context}
Then ask if today's schedule is the same as usual or if anything has changed 
(college 9am-3:55pm, short break at 11am Mon/Wed/Sat, lunch at 12:10pm).
Keep it short and cute. End with something like 'just reply if anything's different today!'"""
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini morning message error: {e}")
        return "Good morning! 🌅💙\n\nDefault schedule today?\nJust reply if anything's different!"


async def parse_schedule_reply(user_message: str) -> dict:
    try:
        model = genai.GenerativeModel(TEXT_MODEL)
        prompt = f"""The user replied to a morning schedule check-in message. 
Parse their reply and extract schedule changes for today.

User's reply: "{user_message}"

Their default schedule:
- College: 9:00 AM to 3:55 PM
- Short break: 11:00 AM (only Mon/Wed/Sat — auto-skipped Tue/Thu/Fri)
- Lunch: 12:10 PM

Extract and return ONLY a JSON object:
{{
  "is_default": true/false,
  "lab_today": true/false/null,
  "busy_until": "HH:MM" or null,
  "free_from": "HH:MM" or null,
  "skip_all": true/false,
  "summary": "one line summary"
}}
No markdown, no explanation."""
        response = model.generate_content(prompt)
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)
    except Exception as e:
        logger.error(f"Schedule parse error: {e}")
        return {"is_default": True, "summary": "Couldn't parse, using default schedule"}


async def generate_schedule_confirmation(parsed: dict) -> str:
    try:
        model = genai.GenerativeModel(TEXT_MODEL)
        prompt = f"""{PERSONA}
You just understood the user's schedule for today: {parsed.get('summary', 'default schedule')}
Send a short cute confirmation. If default, be cheerful. If changed, confirm the change.
1-2 sentences max."""
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        if parsed.get("is_default"):
            return "Got it! Default schedule today 💙"
        return f"Got it! {parsed.get('summary', 'Schedule updated')} 💙"


async def generate_verification_response(verified: bool, drink_count: int) -> str:
    try:
        model = genai.GenerativeModel(TEXT_MODEL)
        if verified:
            prompt = f"""{PERSONA}
He just sent proof that he drank water! React happily.
He's had {drink_count}/8 glasses today.
{'He hit his daily goal!' if drink_count >= 8 else f'He still needs {8 - drink_count} more glasses.'}
Keep it short and sweet."""
        else:
            prompt = f"""{PERSONA}
He sent a photo/video as proof but it doesn't clearly show drinking.
Playfully call him out and ask for better proof. Be funny but firm. Short."""
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Verification response error: {e}")
        if verified:
            return f"Yay!! That's {drink_count}/8 today 💙"
        return "Hmm I can't tell if you actually drank 🤨 Send a clearer photo/video!"


async def verify_proof_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> bool:
    """Verify photo or video frame as proof of drinking"""
    try:
        model = genai.GenerativeModel(VISION_MODEL)
        image_data = {
            "mime_type": mime_type,
            "data": base64.b64encode(image_bytes).decode("utf-8")
        }
        prompt = """Does this image/video show any of the following:
- A person drinking water or any liquid
- A glass/bottle of water being held or recently used
- An empty glass that was clearly just used
- Someone clearly about to drink water

Answer ONLY "YES" or "NO". Be reasonably lenient."""
        response = model.generate_content([prompt, image_data])
        answer = response.text.strip().upper()
        logger.info(f"Vision verification: {answer}")
        return "YES" in answer
    except Exception as e:
        logger.error(f"Vision error: {e}")
        return True