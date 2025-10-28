import json
import time
import random
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://gamdom.com/sports")

    # wait a few seconds for JS to load the data
    time.sleep(random.uniform(3, 5))

    # grab the inline JS state directly
    data = page.evaluate("() => window.__INITIAL_STATE__")
    if not data:
        print("❌ Could not find INITIAL_STATE")
        browser.close()
        exit()

    print("📥 Gamdom data found")

    odds = []
    for sport in data.get("sports", []):
        for league in sport.get("leagues", []):
            for match in league.get("matches", []):
                for market in match.get("markets", []):
                    if market.get("name") not in ("1X2", "Match Winner"):
                        continue
                    for sel in market.get("selections", []):
                        odds.append({
                            "book": "gamdom",
                            "match": f"{match['home']} vs {match['away']}",
                            "market": market["name"],
                            "outcome": sel["name"],
                            "odd": float(sel["odds"])
                        })

    print(f"✅ Parsed {len(odds)} outcomes")
    for o in odds[:10]:  # show first 10 for a quick check
        print(o)

    browser.close()
