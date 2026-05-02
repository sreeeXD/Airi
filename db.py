import os
import logging
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
TIMEZONE = pytz.timezone("Asia/Kolkata")

def get_ist_today():
    return str(datetime.now(TIMEZONE).date())

def get_ist_yesterday():
    return str(datetime.now(TIMEZONE).date() - timedelta(days=1))

def get_conn():
    import pg8000.native
    import urllib.parse
    url = os.getenv("DATABASE_URL")
    r = urllib.parse.urlparse(url.replace("postgresql://", "http://").replace("postgres://", "http://"))
    return pg8000.native.Connection(
        host=r.hostname,
        port=r.port or 5432,
        database=r.path[1:],
        user=r.username,
        password=urllib.parse.unquote(r.password),
        ssl_context=True
    )

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS daily_log (
        date TEXT PRIMARY KEY, drink_count INTEGER DEFAULT 0, goal_met INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS streak (
        id INTEGER PRIMARY KEY, current_streak INTEGER DEFAULT 0, last_goal_date TEXT)""")
    defaults = [("lab_mode","0"),("checkin_done","0"),("busy_until",""),
                ("free_from",""),("skip_all_today","0"),("awaiting_checkin_reply","0")]
    for key, value in defaults:
        c.execute("INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO NOTHING", (key,value))
    c.execute("INSERT INTO streak (id,current_streak) VALUES (1,0) ON CONFLICT (id) DO NOTHING")
    conn.commit(); conn.close()
    logger.info("DB initialized")

def get_setting(key):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=%s", (key,))
    row = c.fetchone(); conn.close()
    return row[0] if row else None

def set_setting(key, value):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s",
              (key, str(value), str(value)))
    conn.commit(); conn.close()

def reset_daily_if_needed():
    today = get_ist_today(); conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO daily_log (date,drink_count) VALUES (%s,0) ON CONFLICT (date) DO NOTHING", (today,))
    conn.commit(); conn.close()

def log_drink():
    today = get_ist_today(); conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO daily_log (date,drink_count) VALUES (%s,0) ON CONFLICT (date) DO NOTHING", (today,))
    c.execute("UPDATE daily_log SET drink_count=drink_count+1 WHERE date=%s", (today,))
    c.execute("SELECT drink_count FROM daily_log WHERE date=%s", (today,))
    row = c.fetchone()
    if row and row[0] >= 8:
        c.execute("UPDATE daily_log SET goal_met=1 WHERE date=%s", (today,))
    conn.commit(); conn.close()

def get_today_count():
    today = get_ist_today(); conn = get_conn(); c = conn.cursor()
    c.execute("SELECT drink_count FROM daily_log WHERE date=%s", (today,))
    row = c.fetchone(); conn.close()
    return row[0] if row else 0

def update_streak():
    yesterday = get_ist_yesterday(); conn = get_conn(); c = conn.cursor()
    c.execute("SELECT goal_met FROM daily_log WHERE date=%s", (yesterday,))
    row = c.fetchone(); goal_met = row and row[0] == 1
    if goal_met:
        c.execute("UPDATE streak SET current_streak=current_streak+1, last_goal_date=%s WHERE id=1", (yesterday,))
    else:
        c.execute("UPDATE streak SET current_streak=0 WHERE id=1")
    conn.commit(); conn.close()

def get_streak():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT current_streak FROM streak WHERE id=1")
    row = c.fetchone(); conn.close()
    return row[0] if row else 0

def set_lab_mode(e): set_setting("lab_mode","1" if e else "0")
def get_lab_mode(): return get_setting("lab_mode")=="1"
def set_checkin_done(d): set_setting("checkin_done","1" if d else "0")
def get_checkin_done(): return get_setting("checkin_done")=="1"
def set_awaiting_checkin_reply(v): set_setting("awaiting_checkin_reply","1" if v else "0")
def get_awaiting_checkin_reply(): return get_setting("awaiting_checkin_reply")=="1"
def set_busy_until(t): set_setting("busy_until", t)
def get_busy_until(): return get_setting("busy_until") or ""
def set_free_from(t): set_setting("free_from", t)
def get_free_from(): return get_setting("free_from") or ""
def set_skip_all(s): set_setting("skip_all_today","1" if s else "0")
def get_skip_all(): return get_setting("skip_all_today")=="1"

def should_send_reminder(hour, minute):
    now_time = hour*60+minute
    if get_skip_all(): return False
    if hour==11 and minute==5:
        if datetime.now(TIMEZONE).weekday() in [1,3,4] or get_lab_mode(): return False
    busy = get_busy_until()
    if busy:
        try:
            bh,bm = map(int,busy.split(":"))
            if now_time <= bh*60+bm: return False
        except: pass
    free = get_free_from()
    if free:
        try:
            fh,fm = map(int,free.split(":"))
            if now_time < fh*60+fm: return False
        except: pass
    return True

def midnight_reset_settings():
    set_lab_mode(False); set_checkin_done(False); set_busy_until("")
    set_free_from(""); set_skip_all(False); set_awaiting_checkin_reply(False)	