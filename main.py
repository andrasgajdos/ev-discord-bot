import os
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

# Load .env
load_dotenv()

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
print("DEBUG: DISCORD_WEBHOOK =", DISCORD_WEBHOOK)
print("DEBUG: ODDS_API_KEY =", "set" if ODDS_API_KEY else "not set")

MIN_EV = 0.00  # temporarily 0 to guarantee Discord messages
SCAN_MINUTES = 3
DB_FILE = "sent.db"

# Sports and esports
SPORTS = [
    "soccer_epl",
    "soccer_la_liga",
    "soccer_serie_a",
    "soccer_bundesliga",
    "soccer_ligue1",
    "basketball_nba",
    "tennis_atp",
    "esports_csgo",
    "esports_dota2",
    "esports_lol"
]

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

# ---------- fetch soft odds ----------
def fetch_gamdom():
    url = "https://gamdom.com/sports/data/matches"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        bets = []
        for sport in data.get("sports", []):
            for match in sport.get("matches", []):
                for market in match.get("markets", []):
                    if market.get("name") != "Match Winner":
                        continue
                    for outcome in market.get("outcomes", []):
                        bets.append({
                            "book": "gamdom",
                            "match": f"{match['home']} v {match['away']}",
                            "market": "Match Winner",
                            "outcome": outcome["name"],
                            "odd": float(outcome["price"])
                        })
        return bets
    except Exception as e:
        print("💥 Gamdom fetch error:", e)
        return []

def fetch_rainbet():
    url = "https://sports-prod.circa.cloud/betby/prematch/events"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        bets = []
        for event in data.get("events", []):
            match_name = f"{event['home']['name']} v {event['away']['name']}"
            for market in event.get("markets", []):
                if market.get("name") != "Match Winner":
                    continue
                for outcome in market.get("outcomes", []):
                    bets.append({
                        "book": "rainbet",
                        "match": match_name,
                        "market": "Match Winner",
                        "outcome": outcome["name"],
                        "odd": float(outcome["price"])
                    })
        return bets
    except Exception as e:
        print("💥 Rainbet fetch error:", e)
        return []

# ---------- fetch sharp odds from Odds API ----------
def fetch_sharp_odds():
    sharp_odds = {}
    try:
        for sport in SPORTS:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?regions=eu&markets=h2h&oddsFormat=decimal&apiKey={ODDS_API_KEY}"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            for event in data:
                match_name = f"{event['home_team']} v {event['away_team']}"
                for bookmaker in event.get("bookmakers", []):
                    if bookmaker.get("key") != "pinnacle":
                        continue
                    for market in bookmaker.get("markets", []):
                        if market["key"] != "h2h":
                            continue
                        for i, outcome in enumerate(market.get("outcomes", [])):
                            sharp_odds[(match_name, outcome["name"])] = float(outcome["price"])
        return sharp_odds
    except Exception as e:
        print("💥 Sharp odds fetch error:", e)
        return sharp_odds

# ---------- EV scanner ----------
def scan():
    print("🔥 ENTERED SCAN FUNCTION")
    init_db()
    print(f"[{datetime.datetime.utcnow():%Y-%m-%d %H:%M:%S}] scanning…")

    soft_odds = fetch_gamdom() + fetch_rainbet()
    sharp_odds = fetch_sharp_odds()
    print(f"✅ fetched {len(soft_odds)} soft bets and {len(sharp_odds)} sharp lines")

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
        print("🚀 Sent alert:", alert_key)

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
