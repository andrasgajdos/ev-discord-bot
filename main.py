import os
import json
import requests
import time
import datetime
import sqlite3
import traceback
import functools
import builtins

# Always flush print output immediately
print = functools.partial(builtins.print, flush=True)

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
print("DEBUG: DISCORD_WEBHOOK =", DISCORD_WEBHOOK)
print("DEBUG: ODDS_API_KEY =", "set" if ODDS_API_KEY else "NOT SET")

MIN_EV = 0.00        # trigger guaranteed messages
SCAN_MINUTES = 3
DB_FILE = "sent.db"

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.90 Safari/537.36"
}

# ---------- helpers ----------
def send_discord(msg):
    if not DISCORD_WEBHOOK:
        print("❌ No Discord webhook set")
        return
    try:
        resp = requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
        print("DEBUG: Discord response:", resp.status_code)
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

def decimal_implied(odd):
    return 1.0 / odd

# ---------- fetch soft odds ----------
def fetch_gamdom():
    url = "https://gamdom.com/sports/data/matches"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        soft_bets = []
        for sport in data.get("sports", []):
            for match in sport.get("matches", []):
                for market in match.get("markets", []):
                    if market.get("type") != "match_winner":
                        continue
                    for outcome in market.get("outcomes", []):
                        soft_bets.append({
                            "book": "gamdom",
                            "match": f"{match['home_team']} v {match['away_team']}",
                            "market": "Match Winner",
                            "outcome": outcome["name"],
                            "odd": float(outcome["american_odds"])
                        })
        return soft_bets
    except Exception as e:
        print("💥 Gamdom fetch error:", e)
        return []

def fetch_rainbet():
    url = "https://sports-prod.circa.cloud/betby/prematch/events"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=False)  # bypass SSL issue
        resp.raise_for_status()
        data = resp.json()
        soft_bets = []
        for event in data.get("events", []):
            match_name = f"{event['home']} v {event['away']}"
            for outcome in event.get("markets", [{}])[0].get("outcomes", []):
                soft_bets.append({
                    "book": "rainbet",
                    "match": match_name,
                    "market": "Match Winner",
                    "outcome": outcome["name"],
                    "odd": float(outcome["price"])
                })
        return soft_bets
    except Exception as e:
        print("💥 Rainbet fetch error:", e)
        return []

# ---------- fetch sharp odds ----------
def fetch_sharp_odds():
    sharp_odds = {}
    for sport in SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            for match in data:
                match_name = f"{match['home_team']} v {match['away_team']}"
                for book in match.get("bookmakers", []):
                    if book["key"] != "pinnacle":  # only sharp
                        continue
                    for market in book.get("markets", []):
                        if market["key"] != "h2h":
                            continue
                        for o, team in enumerate(["home", "away"]):
                            sharp_odds[(match_name, team.capitalize())] = float(market["outcomes"][o]["price"])
        except Exception as e:
            print("💥 Sharp odds fetch error:", e)
    print(f"✅ fetched {len(sharp_odds)} sharp lines")
    return sharp_odds

# ---------- scan ----------
def scan():
    print("🔥 ENTERED SCAN FUNCTION")
    init_db()
    print(f"[{datetime.datetime.utcnow():%Y-%m-%d %H:%M:%S}] scanning…")

    soft_odds = fetch_gamdom() + fetch_rainbet()
    sharp_odds = fetch_sharp_odds()

    if not soft_odds:
        print("⚠️ No soft odds fetched")
    if not sharp_odds:
        print("⚠️ No sharp odds fetched")

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
