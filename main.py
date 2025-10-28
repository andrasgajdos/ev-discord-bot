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

# Always flush print output immediately (important for Render logs)
print = functools.partial(builtins.print, flush=True)

# Load environment variables
load_dotenv()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")  # your Odds API key
print("DEBUG: DISCORD_WEBHOOK =", DISCORD_WEBHOOK)
print("DEBUG: ODDS_API_KEY =", "set" if ODDS_API_KEY else "NOT SET")

# ---------- Settings ----------
MIN_EV = 0.00  # temporary to force a Discord message
SCAN_MINUTES = 3
DB_FILE = "sent.db"

# ---------- Helpers ----------
def decimal_implied(odd):
    return 1.0 / odd

def send_discord(body):
    """Send message to Discord via webhook."""
    if not DISCORD_WEBHOOK:
        print("❌ No webhook set")
        return
    try:
        resp = requests.post(DISCORD_WEBHOOK, json={"content": body}, timeout=10)
        print("DEBUG: Discord response:", resp.status_code, resp.text)
    except Exception as e:
        print("❌ Discord send error:", e)

def init_db():
    """Initialize SQLite DB to track sent alerts."""
    with sqlite3.connect(DB_FILE) as con:
        con.execute("CREATE TABLE IF NOT EXISTS sent(key TEXT PRIMARY KEY)")

def was_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        return con.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() is not None

def mark_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        con.execute("INSERT OR IGNORE INTO sent(key) VALUES(?)", (key,))

def normalize_match_name(name):
    return ''.join(c.lower() for c in name if c.isalnum() or c.isspace()).replace('  ', ' ').strip()

# ---------- Book feeds ----------
def fetch_gamdom():
    url = "https://gamdom.com/sports/data/matches"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        matches = []
        for sport in data.get("sports", []):
            for event in sport.get("events", []):
                match_name = normalize_match_name(f"{event['home']} v {event['away']}")
                outcomes = event.get("markets", [])
                for m in outcomes:
                    if m["name"] != "Match Winner":
                        continue
                    for o in m["outcomes"]:
                        matches.append({
                            "book": "gamdom",
                            "match": match_name,
                            "outcome": o["name"],
                            "odd": float(o["price"])
                        })
        print("📥 Fetched Gamdom odds:", len(matches))
        return matches
    except Exception:
        print("💥 Gamdom fetch error:", traceback.format_exc())
        return []

def fetch_rainbet():
    url = "https://sports-prod.circa.cloud/betby/prematch/events"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        matches = []
        for event in data.get("events", []):
            match_name = normalize_match_name(f"{event['homeTeamName']} v {event['awayTeamName']}")
            for market in event.get("markets", []):
                if market["name"] != "Match Winner":
                    continue
                for o in market.get("outcomes", []):
                    matches.append({
                        "book": "rainbet",
                        "match": match_name,
                        "outcome": o["name"],
                        "odd": float(o["price"])
                    })
        print("📥 Fetched Rainbet odds:", len(matches))
        return matches
    except Exception:
        print("💥 Rainbet fetch error:", traceback.format_exc())
        return []

def fetch_sharp_odds():
    """Fetch Pinnacle/Odds API odds as sharp reference."""
    # Example Odds API endpoint (replace with your real one)
    url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h&oddsFormat=decimal"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        sharp_odds = {}
        for game in data:
            match_name = normalize_match_name(f"{game['home_team']} v {game['away_team']}")
            for outcome, odd in zip(["Home", "Away"], game["bookmakers"][0]["markets"][0]["outcomes"]):
                sharp_odds[(match_name, outcome)] = float(outcome["price"])
        print("📥 Fetched sharp odds:", len(sharp_odds))
        return sharp_odds
    except Exception:
        print("💥 Sharp odds fetch error:", traceback.format_exc())
        return {}

# ---------- EV Scanner ----------
def scan():
    print("🔥 ENTERED SCAN FUNCTION")
    init_db()
    print(f"[{datetime.datetime.utcnow():%Y-%m-%d %H:%M:%S}] scanning…")

    # --- Manual test message ---
    if not was_sent("manual_test"):
        send_discord("Test message")
        mark_sent("manual_test")
        print("🚀 Sent guaranteed test message")

    # --- Fetch odds ---
    soft_odds = fetch_gamdom() + fetch_rainbet()
    sharp_odds = fetch_sharp_odds()

    # --- EV calculation ---
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
            "**{outcome}** {soft:.2f} vs Sharp {sharp:.2f}\n"
            "Stake 1 u → EV +{ev:.1%}"
        ).format(ev, book=row["book"], match=row["match"],
                 outcome=row["outcome"], soft=soft_odd,
                 sharp=sharp_odd, ev=ev)
        send_discord(msg)
        mark_sent(alert_key)
        print("🚀 sent alert:", alert_key)

    print("✅ SCAN FUNCTION FINISHED")

# ---------- Main loop ----------
if __name__ == "__main__":
    while True:
        try:
            print("🔄 starting scan…")
            scan()
            print(f"😴 sleeping {SCAN_MINUTES} min…")
        except Exception:
            print("💥 CRASH:", traceback.format_exc())
        time.sleep(SCAN_MINUTES * 60)
