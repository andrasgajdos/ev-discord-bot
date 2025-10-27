import os, json, requests, time, datetime, sqlite3, traceback
from statistics import median
from dotenv import load_dotenv
load_dotenv()   # reads .env into os.environ

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")  # we’ll add this in Render
MIN_EV          = 0.00                          # 4 % edge threshold
SCAN_MINUTES    = 3
DB_FILE         = "sent.db"

# ---------- helpers ----------
def decimal_implied(odd): return 1.0 / odd

def send_discord(body):
    requests.post(DISCORD_WEBHOOK, json={"content": body}, timeout=10)

def init_db():
    with sqlite3.connect(DB_FILE) as con:
        con.execute("CREATE TABLE IF NOT EXISTS sent(key PRIMARY KEY)")

def was_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        return con.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() is not None

def mark_sent(key):
    with sqlite3.connect(DB_FILE) as con:
        con.execute("INSERT OR IGNORE INTO sent(key) VALUES(?)", (key,))

# ---------- book feeds ----------
def gamdom_feed():
    url = "https://gamdom.com/sports/data/matches"
    print("🔍 fetching GAMDOM…")
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        print("📥 GAMDOM raw payload:", data)
    except Exception as e:
        print("❌ GAMDOM error:", e)
        data = []
    # (rest of your parsing loop stays identical)
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
    url = "https://sports-prod.circa.cloud/betby/prematch/events"
    print("🔍 fetching RAINBET…")
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        print("📥 RAINBET raw payload:", data)
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
    url = "https://www.pinnacle.com/syndication/odds/v1/matchups"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    # build dict (match, outcome) -> best decimal
    best = {}
    for matchup in data:
        key = (matchup["home"], matchup["away"])
        for line in matchup.get("lines", []):
            if line["type"] != "moneyline":
                continue
            for price in line.get("prices", []):
                odd = float(price["decimal"])
                best[(key, price["side"])] = max(odd, best.get((key, price["side"]), 0.0))
    return best

# ---------- ev scanner ----------
def scan():
    print("🔥 ENTERED SCAN FUNCTION")   # <— add this line
    init_db()
    print(f"[{datetime.datetime.utcnow():%Y-%m-%d %H:%M:%S}] scanning…")
    try:
        soft_odds  = gamdom_feed() + rainbet_feed()
        sharp_odds = pinnacle_feed()
    except Exception as e:
        print("feed error:", e)
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

# ---------- loop ----------
if __name__ == "__main__":
    while True:
        try:
            scan()
        except Exception as e:
            print("💥 CRASH:", traceback.format_exc())
        time.sleep(SCAN_MINUTES * 60)
