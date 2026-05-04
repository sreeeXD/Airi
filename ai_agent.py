import os
import base64
import logging
import asyncio
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

TEXT_MODEL = "gemini-1.5-flash-latest"
VISION_MODEL = "gemini-1.5-flash-latest"

# ── API key rotation ──────────────────────────────────────────────────────────

def _load_keys():
    keys = []
    k = os.getenv("GEMINI_API_KEY")
    if k: keys.append(k)
    i = 2
    while True:
        k = os.getenv(f"GEMINI_API_KEY_{i}")
        if not k: break
        keys.append(k)
        i += 1
    logger.info(f"Loaded {len(keys)} Gemini API key(s)")
    return keys

_api_keys = _load_keys()
_key_index = 0


def _rotate_key():
    global _key_index
    if len(_api_keys) > 1:
        _key_index = (_key_index + 1) % len(_api_keys)
        logger.warning(f"Rotated to Gemini API key #{_key_index + 1}")
        return True
    logger.error("All Gemini API keys exhausted!")
    return False


def _get_model(model_name):
    genai.configure(api_key=_api_keys[_key_index])
    return genai.GenerativeModel(model_name)


def _call_gemini(model_name, parts):
    """Sync call with automatic key rotation on quota errors"""
    for _ in range(len(_api_keys)):
        try:
            model = _get_model(model_name)
            return model.generate_content(parts)
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower() or "RESOURCE_EXHAUSTED" in str(e):
                logger.warning(f"Key #{_key_index + 1} quota hit: rotating...")
                if not _rotate_key():
                    raise e
            else:
                raise e
    raise Exception("All Gemini API keys exhausted")


async def _gemini(model_name, parts):
    """Async wrapper for Gemini calls"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _call_gemini(model_name, parts))


# ── Persona ───────────────────────────────────────────────────────────────────

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


# ── Functions ─────────────────────────────────────────────────────────────────

async def generate_reminder(escalation_level: int, drinks_today: int) -> str:
    try:
        level_context = {
            0: "Send a sweet first reminder. Be gentle and loving.",
            1: "He ignored the last reminder. Be a bit more persistent and slightly dramatic.",
            2: "He's ignored twice. Be more firm and worried. Show disappointment but still loving.",
            3: "He's ignored THREE times. FULL girlfriend panic mode. Mention the kidney stones. Guilt trip him lovingly."
        }
        prompt = f"""{PERSONA}

Current situation:
- He's had {drinks_today} glasses of water today (goal is 8)
- Escalation level {escalation_level}: {level_context.get(escalation_level, level_context[3])}

Write ONE reminder message to send him on Telegram right now."""
        response = await _gemini(TEXT_MODEL, [prompt])
        return response.text.strip()
    except Exception as e:
        logger.error(f"generate_reminder error: {e}")
        fallbacks = [
            "Hey! Don't forget to drink water 💧",
            "Babe... water. Now. Please 🥺",
            "Why are you ignoring me?? Drink water!! 😤",
            "DRINK WATER RIGHT NOW I'm not joking 😤💧 Remember the kidney stones?!"
        ]
        return fallbacks[min(escalation_level, 3)]


async def detect_snooze_intent(user_message: str) -> dict:
    try:
        prompt = f"""The user sent this message in response to a water reminder: "{user_message}"

Are they asking to snooze/delay? e.g. "give me 5", "busy rn", "in a bit", "later", "10 mins", "wait"
Are they saying they drank water? e.g. "done", "drank", "finished", "had some", "drinking now"

Return ONLY JSON:
{{"is_snooze": true/false, "is_drank": true/false, "minutes": 10}}
No explanation, no markdown."""
        response = await _gemini(TEXT_MODEL, [prompt])
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)
    except Exception as e:
        logger.error(f"detect_snooze_intent error: {e}")
        return {"is_snooze": False, "is_drank": False, "minutes": 10}


async def generate_snooze_response(minutes: int) -> str:
    try:
        prompt = f"""{PERSONA}
He asked to snooze the water reminder for {minutes} minutes. 
Respond cutely, say you'll check back in {minutes} minutes. 1-2 sentences."""
        response = await _gemini(TEXT_MODEL, [prompt])
        return response.text.strip()
    except:
        return f"Okay fine, {minutes} minutes... but I'm counting! ⏰"


async def generate_good_morning(streak: int) -> str:
    try:
        streak_context = f"He's on a {streak} day streak!" if streak > 0 else "He hasn't started a streak yet."
        prompt = f"""{PERSONA}
Send a cheerful good morning message. {streak_context}
Ask if today's schedule is the same as usual or if anything changed
(college 9am-3:55pm, break at 11am Mon/Wed/Sat, lunch at 12:10pm).
Keep it short. End with 'just reply if anything's different today!'"""
        response = await _gemini(TEXT_MODEL, [prompt])
        return response.text.strip()
    except Exception as e:
        logger.error(f"generate_good_morning error: {e}")
        return "Good morning! 🌅💙\n\nDefault schedule today?\nJust reply if anything's different!"


async def parse_schedule_reply(user_message: str) -> dict:
    try:
        prompt = f"""Parse this schedule reply: "{user_message}"

Default: college 9am-3:55pm, break 11am (Mon/Wed/Sat), lunch 12:10pm

Return ONLY JSON:
{{"is_default": true/false, "lab_today": true/false/null, "busy_until": "HH:MM"/null, "free_from": "HH:MM"/null, "skip_all": true/false, "summary": "one line"}}
No markdown."""
        response = await _gemini(TEXT_MODEL, [prompt])
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)
    except Exception as e:
        logger.error(f"parse_schedule_reply error: {e}")
        return {"is_default": True, "summary": "Using default schedule"}


async def generate_schedule_confirmation(parsed: dict) -> str:
    try:
        prompt = f"""{PERSONA}
Confirm today's schedule: {parsed.get('summary', 'default schedule')}
Short cute confirmation. 1-2 sentences."""
        response = await _gemini(TEXT_MODEL, [prompt])
        return response.text.strip()
    except:
        return f"Got it! {parsed.get('summary', 'Default schedule today')} 💙"


async def generate_verification_response(verified: bool, drink_count: int) -> str:
    try:
        if verified:
            prompt = f"""{PERSONA}
He sent proof he drank water! React happily.
He's had {drink_count}/8 glasses today.
{'Hit daily goal!' if drink_count >= 8 else f'Still needs {8 - drink_count} more.'}
Short and sweet."""
        else:
            prompt = f"""{PERSONA}
His proof photo/video doesn't clearly show drinking.
Playfully call him out, ask for better proof. Funny but firm. Short."""
        response = await _gemini(TEXT_MODEL, [prompt])
        return response.text.strip()
    except Exception as e:
        logger.error(f"generate_verification_response error: {e}")
        if verified:
            return f"Yay!! That's {drink_count}/8 today 💙"
        return "Hmm I can't tell if you actually drank 🤨 Send a clearer photo/video!"


async def verify_proof_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> bool:
    try:
        image_data = {
            "mime_type": mime_type,
            "data": base64.b64encode(image_bytes).decode("utf-8")
        }
        prompt = """Does this image/video show someone drinking water or a water glass/bottle?
Answer ONLY "YES" or "NO". Be reasonably lenient."""
        response = await _gemini(VISION_MODEL, [prompt, image_data])
        answer = response.text.strip().upper()
        logger.info(f"Vision verification: {answer}")
        return "YES" in answer
    except Exception as e:
        logger.error(f"verify_proof_image error: {e}")
        return True