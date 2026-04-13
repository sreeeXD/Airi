import sqlite3
import os
from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)

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

    # Insert defaults
    c.execute("INSERT OR IGNORE INTO streak (id, current_streak) VALUES (1, 0)")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('lab_mode', '0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_reset_date', '')")

    conn.commit()
    conn.close()
    logger.info("Database initialized")


def reset_daily_if_needed():
    """Ensure today's row exists in daily_log"""
    today = str(date.today())
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO daily_log (date, drink_count) VALUES (?, 0)", (today,))
    conn.commit()
    conn.close()


def log_drink():
    today = str(date.today())
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO daily_log (date, drink_count) VALUES (?, 0)", (today,))
    c.execute("UPDATE daily_log SET drink_count = drink_count + 1 WHERE date = ?", (today,))

    # Check if goal met
    c.execute("SELECT drink_count FROM daily_log WHERE date = ?", (today,))
    row = c.fetchone()
    if row and row[0] >= 8:
        c.execute("UPDATE daily_log SET goal_met = 1 WHERE date = ?", (today,))

    conn.commit()
    conn.close()
    logger.info(f"Drink logged for {today}")


def get_today_count() -> int:
    today = str(date.today())
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT drink_count FROM daily_log WHERE date = ?", (today,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def update_streak():
    """Run at midnight — check if yesterday's goal was met and update streak"""
    yesterday = str(date.today() - timedelta(days=1))
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT goal_met FROM daily_log WHERE date = ?", (yesterday,))
    row = c.fetchone()
    goal_met = row and row[0] == 1

    if goal_met:
        c.execute("UPDATE streak SET current_streak = current_streak + 1, last_goal_date = ? WHERE id = 1", (yesterday,))
        logger.info(f"Streak incremented! Yesterday ({yesterday}) goal was met.")
    else:
        c.execute("UPDATE streak SET current_streak = 0 WHERE id = 1")
        logger.info(f"Streak reset. Yesterday ({yesterday}) goal was NOT met.")

    conn.commit()
    conn.close()


def get_streak() -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT current_streak FROM streak WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def set_lab_mode(enabled: bool):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE settings SET value = ? WHERE key = 'lab_mode'", ('1' if enabled else '0',))
    conn.commit()
    conn.close()


def get_lab_mode() -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'lab_mode'")
    row = c.fetchone()
    conn.close()
    return row and row[0] == '1'
