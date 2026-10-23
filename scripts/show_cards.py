import json
import sqlite3
import sys

c = sqlite3.connect("supplier_radar.db")
c.row_factory = sqlite3.Row
rows = c.execute("SELECT identity_key, card_json FROM suppliers").fetchall()
print("total:", len(rows))
for r in rows:
    card = json.loads(r["card_json"])
    name = card["name"][:42]
    ph = len(card["phones"])
    inn = card["inn"][:10] if card["inn"] else "-"
    src = len(card["sources"])
    print(f"- [{card['confidence']}] {name} | ph:{ph} | inn:{inn} | src:{src}")
sys.exit(0)
