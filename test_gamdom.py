import time
import json
import traceback
from playwright.sync_api import sync_playwright

def fetch_gamdom_odds():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            print("🔍 Loading Gamdom sports page…")
            page.goto("https://gamdom.com/sports", timeout=60000)

            # wait a few seconds for JS to render
            time.sleep(5)

            # grab the inline JSON from window.__INITIAL_STATE__
            js_data = page.evaluate("() => window.__INITIAL_STATE__")
            if not js_data or "sports" not in js_data:
                print("❌ No sports data found in Gamdom page")
                return []

            sports = js_data["sports"]
            print(f"📥 Found {len(sports)} sports")

            # parse odds
            odds = []
            for sport in sports:
                for league in sport.get("leagues", []):
                    for match in league.get("matches", []):
                        for market in match.get("markets", []):
                            if market.get("name") not in ("1X2", "Match Winner"):
                                continue
                            for sel in market.get("selections", []):
                                odds.append({
                                    "book": "gamdom",
                                    "match": f"{match.get('home')} vs {match.get('away')}",
                                    "market": market.get("name"),
                                    "outcome": sel.get("name"),
                                    "odd": float(sel.get("odds", 0))
                                })
            print(f"✅ Parsed {len(odds)} outcomes")
            return odds

        except Exception as e:
            print("💥 Gamdom fetch failed:", traceback.format_exc())
            return []
