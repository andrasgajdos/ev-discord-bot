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
    "http://14.251.13.0:8080",
    "http://213.142.156.97:80",
    "http://217.138.18.75:8080",
    "http://38.54.71.67:80",
    "http://43.156.183.112:1080",
    "http://123.30.154.171:7777",
    "http://133.18.234.13:80",
    "http://32.223.6.94:80",
    "http://72.10.160.172:19021",
    "http://190.58.248.86:80",
    "http://90.162.35.34:80",
    "http://50.122.86.118:80",
    "http://35.197.89.213:80",
    "http://188.40.57.101:80",
    "http://192.73.244.36:80",
    "http://23.247.136.254:80",
    "http://3.107.252.199:45157",
    "http://213.157.6.50:80",
    "http://213.33.126.130:80",
    "http://194.158.203.14:80",
    "http://189.202.188.149:80",
    "http://194.219.134.234:80",
    "http://4.245.123.244:80",
    "http://4.195.16.140:80",
    "http://124.108.6.20:8085",
    "http://108.141.130.146:80",
    "http://52.188.28.218:3128",
    "http://143.42.66.91:80",
    "http://198.98.48.76:31280",
    "http://62.99.138.162:80",
    "http://176.108.246.18:10801",
    "http://91.132.92.150:80",
    "http://89.58.55.33:80",
    "http://213.143.113.82:80",
    "http://219.65.73.81:80",
    "http://197.221.234.253:80",
    "http://89.58.57.45:80",
    "http://54.226.156.148:20201",
    "http://5.45.126.128:8080",
    "http://160.251.142.232:80",
    "http://195.114.209.50:80",
    "http://127.0.0.7:80",
    "http://47.252.29.28:11222",
    "http://47.237.92.86:4916",
    "http://195.248.240.25:4443",
    "http://103.214.109.66:80",
    "http://81.169.213.169:8888",
    "http://139.162.78.109:8080",
    "http://41.191.203.167:80",
    "http://51.254.78.223:80",
    "http://47.79.95.122:1122",
    "http://80.74.54.148:3128",
    "http://176.126.103.194:44214",
    "http://0.0.0.0:80",
    "http://97.74.87.226:80",
    "http://180.149.232.63:3301",
    "http://103.125.17.98:8080",
    "http://139.99.237.62:80",
    "http://41.191.203.163:80",
    "http://46.47.197.210:3128",
    "http://8.219.97.248:80",
    "http://168.195.214.41:8800",
    "http://187.111.144.102:8080",
    "http://202.181.16.173:3325",
    "http://121.132.61.211:3128",
    "http://41.191.203.161:80",
    "http://95.173.218.71:8081",
    "http://196.1.93.10:80",
    "http://103.159.46.125:83",
    "http://181.209.125.126:999",
    "http://103.156.248.241:8080",
    "http://201.182.248.149:8080",
    "http://102.0.21.14:8080",
    "http://23.138.88.96:999",
    "http://103.166.158.107:8080",
    "http://103.178.86.86:8080",
    "http://67.43.228.253:3881",
    "http://185.105.230.45:3128",
    "http://198.199.86.11:80",
    "http://219.93.101.62:80",
    "http://138.197.68.35:4857",
    "http://13.212.76.113:9298",
    "http://45.166.93.113:999",
    "http://95.173.218.66:8082",
    "http://210.211.101.120:30000",
    "http://41.89.56.116:3128",
    "http://72.10.160.90:1237",
    "http://103.93.93.178:8181",
    "http://154.65.39.7:80",
    "http://103.65.237.92:5678",
    "http://101.109.245.157:3128",
    "http://103.172.71.25:8080",
    "http://38.95.88.124:999",
    "http://213.212.204.207:1976",
    "http://41.223.119.156:3128",
    "http://38.159.229.92:999",
    "http://138.68.60.8:80",
    "http://217.144.187.208:8118",
    "http://162.240.19.30:80",
    "http://40.192.100.189:8141",
    "http://35.183.64.191:30309",
    "http://37.187.92.9:1026",
    "http://103.189.249.204:1111",
    "http://102.68.79.153:83",
    "http://36.94.232.177:3113",
    "http://176.108.245.247:10804",
    "http://211.230.49.122:3128",
    "http://72.10.160.170:13701",
    "http://47.74.157.194:80",
    "http://14.234.141.1:20499",
    "http://67.43.228.252:21701",
    "http://67.43.236.19:21023",
    "http://209.97.150.167:8080",
    "http://67.43.236.21:11055",
    "http://95.173.218.79:8082",
    "http://38.252.215.110:999",
    "http://103.175.236.18:8080",
    "http://116.203.139.209:5678",
    "http://202.58.77.131:8081",
    "http://103.127.106.209:2024",
    "http://157.66.50.105:8181",
    "http://181.204.106.99:999",
    "http://103.132.54.18:8080",
    "http://124.107.71.252:8082",
    "http://175.213.76.24:80",
    "http://102.223.154.177:8080",
    "http://118.69.183.149:8080",
    "http://103.48.68.141:83",
    "http://8.243.68.10:8080",
    "http://185.41.152.110:3128",
    "http://147.75.34.105:443",
    "http://134.209.29.120:80",
    "http://150.242.12.169:80",
    "http://172.237.80.233:8080",
    "http://103.158.253.13:8382",
    "http://103.155.197.103:8080",
    "http://34.87.84.105:80",
    "http://41.32.39.7:3128",
    "http://47.74.46.81:9080",
    "http://200.174.198.158:8888",
    "http://47.251.74.38:8008",
    "http://181.205.161.187:999",
    "http://186.96.111.214:999",
    "http://47.91.89.3:176",
    "http://47.91.65.23:3128",
    "http://47.89.184.18:3128",
    "http://156.244.11.6:443",
    "http://181.119.103.113:999",
    "http://65.108.159.129:8081",
    "http://186.235.201.10:8080",
    "http://131.72.68.160:40033",
    "http://94.247.129.244:3128",
    "http://43.229.79.217:3128",
    "http://45.77.156.171:9091",
    "http://103.172.196.221:8080",
    "http://154.18.255.11:1111",
    "http://201.139.183.67:10102",
    "http://177.130.25.76:8080",
    "http://24.52.33.75:8080",
    "http://23.237.210.82:80",
    "http://54.221.235.245:3128",
    "http://43.225.151.14:25251",
    "http://201.139.115.38:8082",
    "http://43.209.130.76:109",
    "http://207.254.28.68:2025",
    "http://200.37.252.122:8080",
    "http://190.242.157.215:8080",
    "http://38.194.253.30:999",
    "http://185.236.182.114:999",
    "http://157.100.52.170:999",
    "http://210.87.74.71:8080",
    "http://41.57.6.30:6060",
    "http://38.49.152.103:8080",
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
        "authority": "api.gamdom.onebittech.com",
        "method": "GET",
        "scheme": "https",
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en",
        "origin": "https://sb.gamdom.onebittech.com",
        "priority": "u=1, i",
        "referer": "https://sb.gamdom.onebittech.com/",
        "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
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
                    continue

            for mod in match.get("Modalidades", []):
                market_name = mod.get("Modalidad")
                if not market_name:
                    continue
                for oferta in mod.get("Ofertas", []):
                    odd = oferta.get("CotizacionWeb") or oferta.get("CotizacionTicket")
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

def pinnacle_feed(league_id, retries=3):
    """Scrape Pinnacle odds for a league illegally (free, no API key needed), with retries."""
    for attempt in range(retries):
        url = LEAGUE_MAP.get(league_id)
        if not url:
            return {}

        # Set up headless Chrome with anti-detection
        ua = UserAgent()
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-images")
        options.add_argument(f"--user-agent={ua.random}")
        options.add_argument("--window-size=1920,1080")

        # Rotate proxy (pick random from list)
        proxy = random.choice(PROXIES) if PROXIES else None
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")

        driver = None
        try:
            service = webdriver.ChromeService(executable_path=ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.get(url)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//span[contains(@class, 'participant')]"))
            )

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            events = soup.find_all('div', class_=lambda c: c and ('event' in c or 'row' in c))

            sharp_odds = {}
            for event in events:
                teams = event.find_all('span', class_=lambda c: c and 'participant' in c)
                if len(teams) < 2:
                    continue
                home_team = teams[0].text.strip()
                away_team = teams[1].text.strip()

                odds_elements = event.find_all('span', class_=lambda c: c and 'price' in c)
                if len(odds_elements) < 3:
                    continue
                home_odd = float(odds_elements[0].text.strip())
                away_odd = float(odds_elements[2].text.strip())

                home_norm = normalize_team(home_team)
                away_norm = normalize_team(away_team)
                match_key = f"{home_norm} vs {away_norm}"
                sharp_odds[(match_key, home_team)] = home_odd
                sharp_odds[(match_key, away_team)] = away_odd

            print(f"✅ Scraped {len(sharp_odds)} Pinnacle odds for league {league_id} on attempt {attempt+1}")
            return sharp_odds

        except Exception as e:
            print(f"❌ Attempt {attempt+1} failed for league {league_id}: {e}")
            time.sleep(random.randint(5, 10))
        finally:
            if driver:
                driver.quit()

    print(f"❌ All retries failed for league {league_id}")
    return {}

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
        time.sleep(random.randint(10, 30))  # Anti-ban delay between leagues

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
