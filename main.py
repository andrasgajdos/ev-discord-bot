import os, json, requests, time, datetime, sqlite3, traceback
from statistics import median
from dotenv import load_dotenv
load_dotenv()

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
MIN_EV          = 0.04          # 4 % edge threshold
SCAN_MINUTES    = 3
DB_FILE         = "sent.db"

# ---------- helpers ----------
def decimal_implied(odd): return 1.0 / odd

def send_discord(body):
    requests.post(DISCORD_WEBHOOK, json={"content": body}, timeout=10)

def init_db():
    with sqlite3.connect(DB_FILE) as con:
        con.execute("CREATE TABLE IF NOT EXISTS sent(key TEXT PRIMARY KEY)")

def was_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        return con.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() is not None

def mark_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        con.execute("INSERT OR IGNORE INTO sent(key) VALUES(?)", (key,))

# ---------- book feeds ----------
def gamdom_feed():
    try:
        url = "https://gamdom.com/sports/data/matches"
        print("🔍 fetching GAMDOM…")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print("📥 GAMDOM payload received")
    except Exception as e:
        print("❌ GAMDOM error:", e)
        data = []
    odds = []
    for sport in data:
        for league in sport.get("leagues", []):
            for match in league.get("matches", []):
                for market in match.get("markets", []):
                    if market.get("name") not in ("1X2", "Match Winner"):
                        continue
                    for sel in market.get("selections", []):
                        odds.append({
                            "book": "gamdom",
                            "match": f"{match['home']} vs {match['away']}",
                            "market": market.get("name"),
                            "outcome": sel["name"],
                            "odd": float(sel["odds"])
                        })
    return odds

def rainbet_feed():
    try:
        url = "https://sports-prod.circa.cloud/betby/prematch/events"
        print("🔍 fetching RAINBET…")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print("📥 RAINBET payload received")
    except Exception as e:
        print("❌ RAINBET error:", e)
        data = []
    odds = []
    for event in data:
        for market in event.get("markets", []):
            if market.get("name") not in ("1X2", "Match Winner"):
                continue
            for outcome in market.get("outcomes", []):
                odds.append({
                    "book": "rainbet",
                    "match": event["name"],
                    "market": market.get("name"),
                    "outcome": outcome["name"],
                    "odd": float(outcome["odds"])
                })
    return odds

def pinnacle_feed():
    # Render free plan blocks outbound HTTPS; use dummy sharp prices for now.
    print("📥 PINNACLE dummy (free-plan block)")
    return {("Test v Test", "Home"): 2.40, ("Test v Test", "Away"): 2.55}

# ---------- ev scanner ----------
def scan():
    print("🔥 ENTERED SCAN FUNCTION")
    init_db()
    print(f"[{datetime.datetime.utcnow():%Y-%m-%d %H:%M:%S}] scanning…")
    try:
        print("fetching soft odds…")
        soft_odds  = gamdom_feed() + rainbet_feed()
        print("fetching sharp odds…")
        sharp_odds = pinnacle_feed()
        print("done fetching sharp odds")
    except Exception as e:
        print("💥 feed crash:", traceback.format_exc())
        return

    for row in soft_odds:
        key = (row["match"], row["outcome"])
        if key not in sharp_odds:
            continue
        soft_odd  = row["odd"]
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
            "**{outcome}** {soft:.2f}  vs  Pinnacle {sharp:.2f}\n"
            "Stake 1 u → EV +{ev:.1%}"
        ).format(ev, book=row["book"], match=row["match"], outcome=row["outcome"],
                 soft=soft_odd, sharp=sharp_odd, ev=ev)
        send_discord(msg)
        mark_sent(alert_key)
        print("sent:", alert_key)

    print("✅ SCAN FUNCTION FINISHED")

# ---------- loop ----------
if __name__ == "__main__":
    while True:
        try:
            print("🔄 starting scan…")
            scan()
            print("🔄 scan done, sleeping…")
        except Exception as e:
            print("💥 CRASH:", traceback.format_exc())
        time.sleep(SCAN_MINUTES * 60)
