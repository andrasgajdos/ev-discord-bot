# test_gamdom.py
import time
import random
import json
from playwright.sync_api import sync_playwright, TimeoutError

print("🔍 Starting Gamdom scraper…")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    url = "https://gamdom.com/sports"
    page.goto(url)
    
    # wait a bit for the page to load dynamic content
    try:
        page.wait_for_selector("div[data-testid='sport-card']", timeout=30000)
    except TimeoutError:
        print("⚠️ Timeout waiting for sports cards, continuing anyway…")
    
    # grab page content
    content = page.content()
    print("Page loaded, length:", len(content))
    
    # try to find inline JSON (Gamdom bootstraps state in __INITIAL_STATE__)
    try:
        js_data = page.evaluate("() => window.__INITIAL_STATE__")
        if js_data:
            print("📥 Found inline JSON state")
            # print keys to see structure
            print("Top-level keys:", list(js_data.keys()))
            
            odds = []
            for sport in js_data.get("sports", []):
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
            for o in odds[:10]:  # print first 10 for demo
                print(o)
        else:
            print("⚠️ No inline JSON found, Gamdom may have changed their structure")
    except Exception as e:
        print("❌ Failed to extract inline JSON:", e)

    browser.close()
    print("🔒 Browser closed, done.")
