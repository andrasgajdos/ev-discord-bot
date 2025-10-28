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
            events = r.json()  # Gamdom may return JSON array
            for event in events:
                # XML inside string
                xml_content = event if isinstance(event, str) else event.get("XML")  # adjust if needed
                if not xml_content:
                    continue
                try:
                    root = ET.fromstring(xml_content)
                except:
                    continue

                match_name = root.findtext("Descripcion") or "Unknown match"
                kickoff = root.findtext("FechaPlanInicioPartido") or ""
                try:
                    home, away = [normalize_team(x.strip()) for x in match_name.split(" vs ")]
                except:
                    home = away = ""

                for market in root.findall(".//Modalidades/item"):
                    market_type = market.findtext("Modalidad")
                    if market_type not in ("1X2", "Match Winner"):
                        continue
                    for offer in market.findall("Ofertas/item"):
                        outcome = offer.findtext("OfertaEvento")
                        odd_text = offer.findtext("CotizacionWeb") or offer.findtext("CotizacionTicket")
                        if not outcome or not odd_text:
                            continue
                        odds.append({
                            "book": "Gamdom",
                            "match": match_name,
                            "home": home,
                            "away": away,
                            "market": market_type,
                            "outcome": outcome,
                            "odd": float(odd_text),
                            "kickoff": kickoff
                        })
        except Exception as e:
            print(f"❌ Error fetching Gamdom {league_name}: {e}")
    return odds

# ---------- Pinnacle feed via The Odds API ----------
def pinnacle_feed(sport_key="soccer"):
    odds = {}
    if not THE_ODDS_API_KEY:
        print("❌ THE_ODDS_API_KEY not set")
        return odds
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
            home = normalize_team(event.get("home_team", ""))
            away = normalize_team(event.get("away_team", ""))
            if not home or not away:
                continue
            match_key = f"{home} vs {away}"
            for bookmaker in event.get("bookmakers", []):
                if bookmaker.get("key") != "pinnacle":
                    continue
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        name = outcome.get("name")
                        price = outcome.get("price")
                        if not name or not price:
                            continue
                        odds[(match_key, name)] = price
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
