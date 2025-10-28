import os
import requests
import time
import datetime
import sqlite3
import traceback
import functools
import builtins
import random
import json
from dotenv import load_dotenv

print = functools.partial(builtins.print, flush=True)
load_dotenv()

# ---------- config ----------
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
MIN_EV          = 0.04
SCAN_MINUTES    = 3
DB_FILE         = "sent.db"
USER_AGENT      = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"

# ---------- discord ----------
def send_discord(body):
    if not DISCORD_WEBHOOK:
        print("❌ webhook missing")
        return
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": body}, timeout=10)
        print("📤 Discord", r.status_code)
    except Exception as e:
        print("❌ Discord send:", e)

# ---------- db ----------
def init_db():
    with sqlite3.connect(DB_FILE) as con:
        con.execute("CREATE TABLE IF NOT EXISTS sent(key TEXT PRIMARY KEY)")

def was_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        return con.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() is not None

def mark_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        con.execute("INSERT OR IGNORE INTO sent(key) VALUES(?)", (key,))

# ---------- feeds ----------
def fetch_gamdom():
    """Fetch Gamdom pre-match odds. Tries JSON API first, then falls back to HTML scrape."""
    import re, html, json
    url_api  = "https://gamdom.eu/sports/data/matches"
    url_page = "https://gamdom.eu/sports"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json,text/html",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }

    data = None
    try:
        # ---- Try official JSON endpoint ----
        print("🔍 Gamdom fetch JSON API…")
        time.sleep(random.uniform(1, 3))
        r = requests.get(url_api, headers=headers, timeout=10)
        print("Gamdom API status:", r.status_code, "len:", len(r.text))
        if r.status_code == 200 and len(r.text) > 100:
            data = r.json()
            print("📥 Gamdom JSON API parsed")
        else:
            print("Gamdom API empty or blocked, will try HTML scrape")
    except Exception as e:
        print("Gamdom API fail:", e)

    # ---- Fallback to HTML scrape ----
    if data is None:
        try:
            print("🔍 Gamdom fetch HTML page…")
            time.sleep(random.uniform(2, 4))
            r = requests.get(url_page, headers=headers, timeout=10)
            print("Gamdom page status:", r.status_code, "len:", len(r.text))
            if r.status_code < 200 or len(r.text) < 100:
                print("Gamdom page bad, abort")
                return []

            print("Gamdom first 1000 chars:", r.text[:1000])
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*\})\s*;', r.text, re.DOTALL)
            if not match:
                print("Gamdom no inline JSON found")
                return []

            raw = html.unescape(match.group(1))
            data = json.loads(raw)
            print("📥 Gamdom inline JSON parsed")
        except Exception as e:
            print("❌ Gamdom fallback fail:", traceback.format_exc())
            return []

    # ---- Parse odds ----
    odds = []
    for sport in data.get("sports", []):
        for league in sport.get("leagues", []):
            for match in league.get("matches", []):
                for market in match.get("markets", []):
                    if market.get("name") not in ("1X2", "Match Winner"):
                        continue
                    for sel in market.get("selections", []):
                        try:
                            odds.append({
                                "book": "gamdom",
                                "match": f"{match['home']} vs {match['away']}",
                                "market": market["name"],
                                "outcome": sel["name"],
                                "odd": float(sel["odds"])
                            })
                        except Exception as e:
                            print("❌ Gamdom parse error:", e)
    print(f"✅ Gamdom parsed {len(odds)} outcomes")
    return odds

def fetch_pinnacle():
    """Dummy sharp reference (replace with real scrape later)."""
    print("📥 Pinnacle dummy")
    return {("Test v Test", "Home"): 2.40, ("Test v Test", "Away"): 2.55}

# ---------- EV scanner ----------
def scan():
    print("🔥 SCAN START")
    init_db()
    sharp_odds = fetch_pinnacle()
    soft_odds  = fetch_gamdom()

    for row in soft_odds:
        key = (row["match"], row["outcome"])
        if key not in sharp_odds:
            continue
        soft_odd  = row["odd"]
        sharp_odd = sharp_odds[key]
        ev = (sharp_odd / soft_odd) - 1
        if ev < MIN_EV:
            continue
        alert_key = f"gamdom {key[0]} {key[1]} {datetime.date.today()}"
        if was_sent(alert_key):
            continue
        msg = (
            "@everyone +EV {:.1%}\n"
            "**Gamdom** {match}\n"
            "**{outcome}** {soft:.2f}  vs  Pinnacle {sharp:.2f}\n"
            "Stake 1 u → EV +{ev:.1%}"
        ).format(ev, match=row["match"], outcome=row["outcome"],
                 soft=soft_odd, sharp=sharp_odd, ev=ev)
        send_discord(msg)
        mark_sent(alert_key)
        print("🚀 sent alert:", alert_key)
    print("✅ SCAN FINISHED")

# ---------- main loop ----------
if __name__ == "__main__":
    while True:
        try:
            scan()
        except Exception:
            print("💥 outer crash:", traceback.format_exc())
        time.sleep(SCAN_MINUTES * 60)
