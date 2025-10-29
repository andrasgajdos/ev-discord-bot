import os
import requests
import time
import datetime
import sqlite3
import functools
import builtins
import unicodedata
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from undetected_chromedriver import Chrome, ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
import random

# Always flush print output
print = functools.partial(builtins.print, flush=True)

# Load environment
load_dotenv()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# ---------- Config ----------
MIN_EV = 0.0
SCAN_MINUTES = 3
DB_FILE = "sent.db"

# Mapping Gamdom league IDs → Pinnacle league URLs
LEAGUE_MAP = {
    56: "https://www.pinnacle.com/en/soccer/italy-serie-a/matchups/",  # Serie A
    90: "https://www.pinnacle.com/en/soccer/germany-bundesliga/matchups/",  # Bundesliga
    95: "https://www.pinnacle.com/en/soccer/england-premier-league/matchups/",  # EPL
    29: "https://www.pinnacle.com/en/soccer/spain-la-liga/matchups/",  # La Liga
    116: "https://www.pinnacle.com/en/soccer/france-ligue-1/matchups/",  # Ligue 1
}

GAMDOM_LEAGUES = {
    56: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=56",
    90: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=90",
    95: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=95",
    29: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=29",
    116: "https://api.gamdom.onebittech.com/api/partidos?IdInstanciaTorneo=116",
}

# List of proxies for rotation (replace with real ones; test for speed)
PROXIES = [
    "http://1.2.3.4:8080",  # Example; get from free-proxy-list.net or paid
    "http://5.6.7.8:3128",
    # Add 10-20 more here
]

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

def pinnacle_feed(league_id):
    """Scrape Pinnacle odds for a league illegally (free, no API key needed)."""
    url = LEAGUE_MAP.get(league_id)
    if not url:
        return {}

    # Set up headless Chrome with anti-detection
    ua = UserAgent()
    options = ChromeOptions()
    options.add_argument("--headless")  # No UI
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-images")  # Faster loading
    options.add_argument(f"--user-agent={ua.random}")  # Rotate UA
    options.add_argument("--window-size=1920,1080")

    # Rotate proxy (pick random from list)
    proxy = random.choice(PROXIES) if PROXIES else None
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")

    driver = None
    sharp_odds = {}
    try:
        driver = Chrome(options=options, driver_executable_path=ChromeDriverManager().install())
        driver.get(url)
        # Wait for odds to load (look for a common element like participant or price)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//span[contains(@class, 'participant')]"))  # Better: wait for team names
        )

        # Parse the page
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # Pinnacle uses divs or trs for events; try div with class containing 'event' or 'row'
        events = soup.find_all('div', class_=lambda c: c and ('event' in c or 'row' in c))  # Flexible match

        for event in events:
            # Teams: spans with 'participant' in class
            teams = event.find_all('span', class_=lambda c: c and 'participant' in c)
            if len(teams) < 2:
                continue
            home_team = teams[0].text.strip()
            away_team = teams[1].text.strip()

            # Odds: spans with 'price' in class (Pinnacle shows 1/X/2 for h2h)
            odds_elements = event.find_all('span', class_=lambda c: c and 'price' in c)
            if len(odds_elements) < 3:
                continue
            home_odd = float(odds_elements[0].text.strip())
            draw_odd = float(odds_elements[1].text.strip())
            away_odd = float(odds_elements[2].text.strip())

            # Normalize and store
            home_norm = normalize_team(home_team)
            away_norm = normalize_team(away_team)
            match_key = f"{home_norm} vs {away_norm}"
            sharp_odds[(match_key, home_team)] = home_odd
            sharp_odds[(match_key, away_team)] = away_odd

    except Exception as e:
        print(f"❌ Pinnacle scrape error for league {league_id}: {e}")
    finally:
        if driver:
            driver.quit()

    print(f"✅ Scraped {len(sharp_odds)} Pinnacle odds for league {league_id}")
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
        sharp = pinnacle_feed(league_id)
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
