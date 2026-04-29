import sqlite3, json
from pathlib import Path
p = Path('kleinanzeigen_listings.db')
if not p.exists():
    print('DB not found:', p)
    raise SystemExit(1)
con = sqlite3.connect(str(p))
con.row_factory = sqlite3.Row
rows = con.execute('SELECT subscription_id,email,frequency,max_price_eur,is_active,last_sent_at,next_send_at FROM user_subscriptions').fetchall()
print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
con.close()
