import time
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    print("🔍 Navigating to Gamdom...")
    page.goto("https://gamdom.com/sports")
    
    # Wait a few seconds for JavaScript to populate window.__INITIAL_STATE__
    time.sleep(5)

    # Grab the live state directly from the page
    state = page.evaluate("() => window.__INITIAL_STATE__")
    if not state:
        print("❌ No __INITIAL_STATE__ found")
        browser.close()
        exit()

    print("📥 Found __INITIAL_STATE__")
    
    odds = []
    for sport in state.get("sports", []):
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
    for o in odds[:10]:  # print first 10 as a sample
        print(o)

    browser.close()
