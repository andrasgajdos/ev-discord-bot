# test_gamdom.py

import requests
import json

def fetch_gamdom_odds():
    url = "https://gamdom.eu/sports/partidos"
    try:
        print("🔍 Fetching Gamdom odds…")
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"❌ Request failed, status code: {r.status_code}")
            return None
        
        data = r.json()
        print(f"✅ Success! Fetched {len(data.get('matches', []))} matches")  # number of matches
        return data

    except Exception as e:
        print("❌ Error fetching Gamdom odds:", e)
        return None

if __name__ == "__main__":
    matches = fetch_gamdom_odds()
    if matches:
        # Print first match as a quick test
        if matches.get("matches"):
            first = matches["matches"][0]
            print("First match example:")
            print(json.dumps(first, indent=2))
        else:
            print("No matches found in response.")
    else:
        print("Failed to fetch Gamdom data.")
