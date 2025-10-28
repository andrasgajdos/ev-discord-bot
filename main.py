import os
import requests
import time
import datetime
import sqlite3
import functools
import builtins
import unicodedata
from dotenv import load_dotenv

# Always flush print output
print = functools.partial(builtins.print, flush=True)

# Load environment
load_dotenv()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
ODDSAPI_KEY = os.getenv("THE_ODDS_API_KEY")

print("DEBUG: Odds API Key loaded:", ODDSAPI_KEY is not None)

# ---------- Config ----------
MIN_EV = 0.0
SCAN_MINUTES = 3
DB_FILE = "sent.db"

# Mapping Gamdom league IDs → Pinnacle sport_keys
LEAGUE_MAP = {
    56: "soccer_italy_serie_a",
    90: "soccer_germany_bundesliga",
    95: "soccer_epl",
    29: "soccer_spain_la_liga",
    116: "soccer_france_ligue_one",
}

GAMDOM_LEAGUES = {
    56: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=56",
    90: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=90",
    95: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=95",
    29: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=29",
    116: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=116",
}

# ---------- helpers ----------
def send_discord(msg):
    if not DISCORD_WEBHOOK:
        print("❌ No webhook set")
        return
    try:
        resp = requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
        print("Discord response:", resp.status_code)
    except Exception as e:
        print("❌ Discord error:", e)

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
    """Lowercase, strip accents, remove extra spaces."""
    name = name.lower().strip()
    name = ''.join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c))
    return name

# ---------- feeds ----------
def gamdom_feed():
    """Fetch all matches from Gamdom and parse odds."""
    all_odds = []
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://sb.gamdom.onebittech.com",
        "Accept-Language": "en",
    }

    for league_id, url in GAMDOM_LEAGUES.items():
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"❌ Gamdom fetch error for league {league_id}:", e)
            continue

        matches = data.get("matches") if isinstance(data, dict) else data
        if not matches:
            print(f"⚠️ No matches found for league {league_id}")
            continue

        for match in matches:
            home_name = match.get("EquipoLocalNombre", "")
            away_name = match.get("EquipoVisitanteNombre", "")
            if not home_name or not away_name:
                desc = match.get("Descripcion", "")
                if " vs " in desc:
                    home_name, away_name = [x.strip() for x in desc.split(" vs ")]
                else:
                    continue  # skip if no proper names

            for mod in match.get("Modalidades", []):
                market_name = mod.get("Modalidad")
                if not market_name:
                    continue
                for oferta in mod.get("Ofertas", []):
                    odd = oferta.get("CotizacionTicket")
                    if not odd:
                        continue

                    localia = oferta.get("Localia")
                    if localia == 1:
                        outcome = home_name
                    elif localia == 2:
                        outcome = away_name
                    else:
                        outcome = oferta.get("OfertaEvento")
                        if not outcome:
                            continue

                    all_odds.append({
                        "league_id": league_id,
                        "match": f"{home_name} vs {away_name}",
                        "home": home_name,
                        "away": away_name,
                        "market": market_name,
                        "outcome": outcome,
                        "odd": float(odd)
                    })

    print(f"✅ Total Gamdom odds fetched: {len(all_odds)}")
    return all_odds

def pinnacle_feed(league_id, market_type="h2h"):
    """Fetch Pinnacle odds for a league and specific market (h2h, totals, btts)."""
    sport_key = LEAGUE_MAP.get(league_id)
    if not sport_key or not ODDSAPI_KEY:
        return {}

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "regions": "eu",
        "markets": market_type,
        "oddsFormat": "decimal",
        "bookmakers": "pinnacle",
        "apiKey": ODDSAPI_KEY
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"❌ Pinnacle fetch error for {sport_key}: {e}")
        return {}

    sharp_odds = {}
    for m in data:
        home = normalize_team(m["home_team"])
        away = normalize_team(m["away_team"])
        for book in m.get("bookmakers", []):
            if book["key"] != "pinnacle":
                continue
            for market in book.get("markets", []):
                if market["key"] != market_type:
                    continue
                for outcome in market.get("outcomes", []):
                    key = (f"{home} vs {away}", outcome["name"])
                    sharp_odds[key] = outcome["price"]
    return sharp_odds

# ---------- EV scan ----------
def scan():
    init_db()
    print(f"[{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M:%S}] scanning…")

    soft_odds = gamdom_feed()
    if not soft_odds:
        print("❌ No Gamdom odds fetched")
        return

    leagues = set(row["league_id"] for row in soft_odds)
    all_sharp = {}
    for league_id in leagues:
        sharp = pinnacle_feed(league_id, market_type="h2h")
        if sharp:
            all_sharp.update(sharp)

    for row in soft_odds:
        key = (normalize_team(f"{row['home']} vs {row['away']}"), row["outcome"])
        if key not in all_sharp:
            continue
        soft_odd = row["odd"]
        sharp_odd = all_sharp[key]
        ev = (sharp_odd / soft_odd) - 1
        if ev < MIN_EV:
            continue
        alert_key = f"{row['match']} {row['outcome']} {datetime.date.today()}"
        if was_sent(alert_key):
            continue
        msg = (
            f"@everyone +EV {ev:.1%}\n"
            f"**Gamdom** {row['match']}\n"
            f"**{row['outcome']}** {soft_odd:.2f} vs Pinnacle {sharp_odd:.2f}\n"
            f"Stake 1 u → EV +{ev:.1%}"
        )
        send_discord(msg)
        mark_sent(alert_key)
        print("🚀 Sent alert:", alert_key)

    print("✅ Scan finished")

# ---------- main loop ----------
if __name__ == "__main__":
    while True:
        try:
            scan()
            print(f"😴 sleeping {SCAN_MINUTES} min…")
        except Exception as e:
            print("💥 Crash:", e)
        time.sleep(SCAN_MINUTES * 60)
