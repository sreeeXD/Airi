import sqlite3
import os
from datetime import datetime, timedelta
import logging
import pytz
 
logger = logging.getLogger(__name__)
TIMEZONE = pytz.timezone("Asia/Kolkata")
 
def get_ist_today():
    return str(datetime.now(TIMEZONE).date())
 
def get_ist_yesterday():
    return str(datetime.now(TIMEZONE).date() - timedelta(days=1))
 
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "hydration.db")
 
 
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)
 
 
def init_db():
    conn = get_conn()
    c = conn.cursor()
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_log (
            date TEXT PRIMARY KEY,
            drink_count INTEGER DEFAULT 0,
            goal_met INTEGER DEFAULT 0
        )
    """)
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS streak (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            current_streak INTEGER DEFAULT 0,
            last_goal_date TEXT
        )
    """)
 
    defaults = [
        ("lab_mode", "0"),
        ("checkin_done", "0"),
        ("busy_until", ""),
        ("free_from", ""),
        ("skip_all_today", "0"),
        ("awaiting_checkin_reply", "0"),
    ]
    for key, value in defaults:
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
 
    c.execute("INSERT OR IGNORE INTO streak (id, current_streak) VALUES (1, 0)")
 
    conn.commit()
    conn.close()
    logger.info("Database initialized")
 
 
def get_setting(key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None
 
 
def set_setting(key, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()
 
 
def reset_daily_if_needed():
    today = get_ist_today()
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO daily_log (date, drink_count) VALUES (?, 0)", (today,))
    conn.commit()
    conn.close()
 
 
def log_drink():
    today = get_ist_today()
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO daily_log (date, drink_count) VALUES (?, 0)", (today,))
    c.execute("UPDATE daily_log SET drink_count = drink_count + 1 WHERE date = ?", (today,))
    c.execute("SELECT drink_count FROM daily_log WHERE date = ?", (today,))
    row = c.fetchone()
    if row and row[0] >= 8:
        c.execute("UPDATE daily_log SET goal_met = 1 WHERE date = ?", (today,))
    conn.commit()
    conn.close()
 
 
def get_today_count():
    today = get_ist_today()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT drink_count FROM daily_log WHERE date = ?", (today,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0
 
 
def update_streak():
    yesterday = get_ist_yesterday()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT goal_met FROM daily_log WHERE date = ?", (yesterday,))
    row = c.fetchone()
    goal_met = row and row[0] == 1
    if goal_met:
        c.execute("UPDATE streak SET current_streak = current_streak + 1, last_goal_date = ? WHERE id = 1", (yesterday,))
    else:
        c.execute("UPDATE streak SET current_streak = 0 WHERE id = 1")
    conn.commit()
    conn.close()
 
 
def get_streak():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT current_streak FROM streak WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0
 
 
def set_lab_mode(enabled: bool):
    set_setting("lab_mode", "1" if enabled else "0")
 
 
def get_lab_mode():
    return get_setting("lab_mode") == "1"
 
 
def set_checkin_done(done: bool):
    set_setting("checkin_done", "1" if done else "0")
 
 
def get_checkin_done():
    return get_setting("checkin_done") == "1"
 
 
def set_awaiting_checkin_reply(val: bool):
    set_setting("awaiting_checkin_reply", "1" if val else "0")
 
 
def get_awaiting_checkin_reply():
    return get_setting("awaiting_checkin_reply") == "1"
 
 
def set_busy_until(time_str: str):
    set_setting("busy_until", time_str)
 
 
def get_busy_until():
    return get_setting("busy_until") or ""
 
 
def set_free_from(time_str: str):
    set_setting("free_from", time_str)
 
 
def get_free_from():
    return get_setting("free_from") or ""
 
 
def set_skip_all(skip: bool):
    set_setting("skip_all_today", "1" if skip else "0")
 
 
def get_skip_all():
    return get_setting("skip_all_today") == "1"
 
 
def should_send_reminder(hour: int, minute: int) -> bool:
    """Check if a reminder at HH:MM should be sent based on today's schedule"""
    now_time = hour * 60 + minute
 
    if get_skip_all():
        return False
 
    if hour == 11 and minute == 5:
        weekday = datetime.now(TIMEZONE).weekday()
        if weekday in [1, 3, 4] or get_lab_mode(): # Tue, Thu, Fri are continuous labs
            logger.info("Skipping 11:05 reminder — lab day (auto or manual)")
            return False
 
    busy_until = get_busy_until()
    if busy_until:
        try:
            bh, bm = map(int, busy_until.split(":"))
            if now_time <= bh * 60 + bm:
                logger.info(f"Skipping {hour:02d}:{minute:02d} — busy until {busy_until}")
                return False
        except Exception:
            pass
 
    free_from = get_free_from()
    if free_from:
        try:
            fh, fm = map(int, free_from.split(":"))
            if now_time < fh * 60 + fm:
                logger.info(f"Skipping {hour:02d}:{minute:02d} — not free until {free_from}")
                return False
        except Exception:
            pass
 
    return True
 
 
def midnight_reset_settings():
    set_lab_mode(False)
    set_checkin_done(False)
    set_busy_until("")
    set_free_from("")
    set_skip_all(False)
    set_awaiting_checkin_reply(False)
 