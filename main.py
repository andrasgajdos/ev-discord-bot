import os
import json
import requests
import time
import datetime
import sqlite3
import traceback
import functools
import builtins
from statistics import median
from dotenv import load_dotenv

# Always flush print output immediately (important for Render logs)
print = functools.partial(builtins.print, flush=True)

# Load .env
load_dotenv()

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
MIN_EV = 0.04        # 4% edge threshold
SCAN_MINUTES = 3
DB_FILE = "sent.db"

# ---------- helpers ----------
def decimal_implied(odd):
    return 1.0 / odd

def send_discord(body):
    """Send message to Discord via webhook."""
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": body}, timeout=10)
    except Exception as e:
        print("❌ Discord send error:", e)

def init_db():
    """Initialize SQLite DB to track sent alerts."""
    with sqlite3.connect(DB_FILE) as con:
        con.execute("CREATE TABLE IF NOT EXISTS sent(key TEXT PRIMARY KEY)")

def was_sent(key):
    """Check if alert already sent."""
    with sqlite3.connect(DB_FILE) as con:
        return con.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() is not None

def mark_sent(key):
    """Mark alert as sent."""
    with sqlite3.connect(DB_FILE) as con:
        con.execute("INSERT OR IGNORE INTO sent(key) VALUES(?)", (key,))

# ---------- book feeds (dummy) ----------
def gamdom_feed():
    """Dummy Gamdom odds feed."""
    print("📥 GAMDOM dummy feed")
    return [
        {"book": "gamdom", "match": "Test v Test", "market": "Match Winner", "outcome": "Home", "odd": 2.50}
    ]

def rainbet_feed():
    """Dummy Rainbet odds feed."""
    print("📥 RAINBET dummy feed")
    return [
        {"book": "rainbet", "match": "Test v Test", "market": "Match Winner", "outcome": "Away", "odd": 2.60}
    ]

def pinnacle_feed():
    """Dummy Pinnacle sharp odds feed (free plan blocks HTTPS)."""
    print("📥 PINNACLE dummy feed (free-plan block)")
    return {
        ("Test v Test", "Home"): 2.40,
        ("Test v Test", "Away"): 2.55
    }

# ---------- EV scanner ----------
def scan():
    print("🔥 ENTERED SCAN FUNCTION")
    init_db()
