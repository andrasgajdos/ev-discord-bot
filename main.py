import os
import requests
import time
import datetime
import sqlite3
import traceback
import functools
import builtins
import unicodedata
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

# Flush print immediately
print = functools.partial(builtins.print, flush=True)

# Load .env
load_dotenv()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
THE_ODDS_API_KEY = os.getenv("THE_ODDS_API_KEY")

# Config
MIN_EV = 0.00  # alert bets with >5% EV
SCAN_MINUTES = 3
DB_FILE = "sent.db"

# Gamdom league IDs
LEAGUES = {
    "Premier League": 95,
    "Bundesliga": 90,
    "La Liga": 29,
    "Serie A": 56,
    "Champions League": 74,
    "NBA": 30,
    "GT League": 655,
}

# ---------- helpers ----------
def send_discord(body):
    if not DISCORD_WEBHOOK:
        print("❌ No webhook set")
        return
    try:
        resp = requests.post(DISCORD_WEBHOOK, json={"content": body}, timeout=10)
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

def normalize_team(name):
    name = name.lower().strip()
    name = ''.join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c))
    return name

# ---------- Gamdom feed (XML) ----------
def gamdom_feed():
    odds = []
    for league_name, league_id in LEAGUES.items():
        url = f"https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo={league_id}"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            events = r.json()  # Gamdom sometimes returns JSON with XML inside; handle accordingly
            for event in events:
                # If XML inside string, parse:
                if isinstance(event, str) and event.strip().startswith("<"):
                    root = ET.fromstring(event)
                else:
                    root = event  # assume dict
                match_name = root.get("Descripcion") or root.get("name") or "Unknown match"
                kickoff = root.get("FechaPlanInicioPartido") or ""
                for market in root.get("Modalidades", []):
                    for m_item in market.get("item", []):
                        market_type = m_item.get("Modalidad") or m_item.get("name")
                        if market_type not in ("1X2", "Match Winner"):
                            continue
                        for offer in m_item.get("Ofertas", {}).get("item", []):
                            outcome = offer.get("OfertaEvento") or offer.get("name")
                            odd = offer.get("CotizacionWeb") or offer.get("CotizacionTicket") or offer.get("odds")
                            if not odd:
                                continue
                            odds.append({
                                "book": "Gamdom",
                                "match": match_name,
                                "home": normalize_team(match_name.split(" vs ")[0]),
                                "away": normalize_team(match_name.split(" vs ")[1]),
                                "market": market_type,
                                "outcome": outcome,
                                "odd": float(odd),
                                "kickoff": kickoff
                            })
        except Exception as e:
            print(f"❌ Error fetching Gamdom {league_name}: {e}")
    return odds

# ---------- Pinnacle feed via The Odds API ----------
def pinnacle_feed(sport_key="soccer"):
    odds = {}
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        'apiKey': THE_ODDS_API_KEY,
        'regions': 'eu',
        'markets': 'h2h',
        'oddsFormat': 'decimal',
        'bookmakers': 'pinnacle'
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        for event in data:
            home_norm = normalize_team(event['home_team'])
            away_norm = normalize_team(event['away_team'])
            match_key = f"{home_norm} vs {away_norm}"
            for bookmaker in event.get("bookmakers", []):
                if bookmaker["key"] != "pinnacle":
                    continue
                for market in bookmaker.get("markets", []):
                    if market["key"] != "h2h":
                        continue
                    for outcome, odd in zip(market["outcomes"], market["odds"]):
                        odds[(match_key, outcome)] = odd
    except Exception as e:
        print("❌ Pinnacle feed error:", e)
    return odds

# ---------- EV scanner ----------
def scan():
    print(f"[{datetime.datetime.utcnow():%Y-%m-%d %H:%M:%S}] scanning…")
    init_db()
    try:
        soft_odds = gamdom_feed()
        sharp_odds = pinnacle_feed()
    except Exception:
        print("💥 feed crash:", traceback.format_exc())
        return

    for row in soft_odds:
        key = (f"{row['home']} vs {row['away']}", row["outcome"])
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

# ---------- main loop ----------
if __name__ == "__main__":
    while True:
        try:
            scan()
        except Exception:
            print("💥 CRASH:", traceback.format_exc())
        time.sleep(SCAN_MINUTES * 60)
