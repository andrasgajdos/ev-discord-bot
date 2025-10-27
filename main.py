import os
import json
import requests
import time
import datetime
import sqlite3
import traceback
import functools
import builtins
from dotenv import load_dotenv

# Always flush print output immediately
print = functools.partial(builtins.print, flush=True)

# Load .env
load_dotenv()

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
print("DEBUG: DISCORD_WEBHOOK =", DISCORD_WEBHOOK)

# ---------- MANUAL TEST ----------
if DISCORD_WEBHOOK:
    try:
        resp = requests.post(DISCORD_WEBHOOK, json={"content": "Test message"}, timeout=10)
        print("Manual Discord test:", resp.status_code, resp.text)
    except Exception as e:
        print("Manual Discord test failed:", e)
else:
    print("❌ DISCORD_WEBHOOK not set")

MIN_EV = 0.00  # temporarily 0 to trigger dummy alert
SCAN_MINUTES = 3
DB_FILE = "sent.db"

# ---------- helpers ----------
def send_discord(body):
    if not DISCORD_WEBHOOK:
        print("❌ No webhook set, cannot send Discord message")
        return
    try:
        resp = requests.post(DISCORD_WEBHOOK, json={"content": body}, timeout=10)
        print("DEBUG: Discord response:", resp.status_code, resp.text)
    except Exception as e:
        print("❌ Discord send error:", e)

def init_db():
    with sqlite3.connect(DB_FILE) as con:
        con.execute("CREATE TABLE IF NOT EXISTS sent(key TEXT PRIMARY KEY)")

def was_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        return con.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() is not None

def mark_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        con.execute("INSERT OR IGNORE INTO sent(key) VALUES(?)", (key,))

# ---------- book feeds (dummy, +EV guaranteed) ----------
def gamdom_feed():
    print("📥 GAMDOM dummy feed")
    return [
        {"book": "gamdom", "match": "Test v Test", "market": "Match Winner", "outcome": "Home", "odd": 2.20}
    ]

def rainbet_feed():
    print("📥 RAINBET dummy feed")
    return [
        {"book": "rainbet", "match": "Test v Test", "market": "Match Winner", "outcome": "Away", "odd": 2.50}
    ]

def pinnacle_feed():
    print("📥 PINNACLE dummy feed")
    return {
        ("Test v Test", "Home"): 2.40,
        ("Test v Test", "Away"): 2.55
    }

# ---------- EV scanner ----------
def scan():
    print("🔥 ENTERED SCAN FUNCTION")
    init_db()
    print(f"[{datetime.datetime.utcnow():%Y-%m-%d %H:%M:%S}] scanning…")

    try:
        print("🔍 fetching soft odds…")
        soft_odds = gamdom_feed() + rainbet_feed()
        print("🔍 fetching sharp odds…")
        sharp_odds = pinnacle_feed()
        print("✅ done fetching odds")
    except Exception:
        print("💥 feed crash:", traceback.format_exc())
        return

    for row in soft_odds:
        key = (row["match"], row["outcome"])
        if key not in sharp_odds:
            continue
        soft_odd = row["odd"]
        sharp_odd = sharp_odds[key]
        ev = (sharp_odd / soft_odd) - 1
        if ev < MIN_EV:
            continue
        alert_key = f"{row['book']} {key[0]} {key[1]} {datetime.date.today()}"
        if was_sent(alert_key):
            continue
        msg = (
            "@everyone +EV {:.1%}\n"
            "**{book}** {match}\n"
            "**{outcome}** {soft:.2f} vs Pinnacle {sharp:.2f}\n"
            "Stake 1 u → EV +{ev:.1%}"
        ).format(ev, book=row["book"], match=row["match"],
                 outcome=row["outcome"], soft=soft_odd,
                 sharp=sharp_odd, ev=ev)
        send_discord(msg)
        mark_sent(alert_key)
        print("🚀 sent alert:", alert_key)

    print("✅ SCAN FUNCTION FINISHED")

# ---------- main loop ----------
if __name__ == "__main__":
    while True:
        try:
            print("🔄 starting scan…")
            scan()
            print(f"😴 sleeping {SCAN_MINUTES} min…")
        except Exception as e:
            print("💥 CRASH:", traceback.format_exc())
        time.sleep(SCAN_MINUTES * 60)
