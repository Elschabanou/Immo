import sqlite3
from pathlib import Path

DB = Path('kleinanzeigen_listings.db')
OUT = Path('migration_batches')
BATCH_SIZE = 100
OUT.mkdir(exist_ok=True)

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def sql_value(value):
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"

def export_table(table, batch_size=None):
    cols = [row[1] for row in cur.execute(f'PRAGMA table_info({table})').fetchall()]
    rows = cur.execute(f'SELECT * FROM {table}').fetchall()
    if batch_size is None:
        batch_size = max(1, len(rows))
    if not rows:
        (OUT / f'{table}.sql').write_text(f'-- no rows for {table}\n', encoding='utf-8')
        return 0, 0
    written = 0
    batch_no = 0
    for i in range(0, len(rows), batch_size):
        batch_no += 1
        chunk = rows[i:i+batch_size]
        values_sql = []
        for row in chunk:
            values_sql.append('(' + ', '.join(sql_value(row[col]) for col in cols) + ')')
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n" + ',\n'.join(values_sql) + ';\n'
        filename = OUT / (f'{table}.sql' if len(rows) <= batch_size else f'{table}_batch_{batch_no:03d}.sql')
        filename.write_text(sql, encoding='utf-8')
        written += len(chunk)
    return written, batch_no

summary = {}
summary['listings'] = export_table('listings', BATCH_SIZE)
summary['crawler_state'] = export_table('crawler_state')
summary['user_subscriptions'] = export_table('user_subscriptions')
conn.close()
for table, (count, batches) in summary.items():
    print(table, count, batches)
