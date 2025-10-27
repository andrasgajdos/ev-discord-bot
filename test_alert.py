import os, requests, datetime
msg = f"🧪 EV-bot pipe test — {datetime.datetime.utcnow():%H:%M:%S} UTC"
requests.post(os.getenv("DISCORD_WEBHOOK"), json={"content": msg})
