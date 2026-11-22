import os, sys
sys.path.append('app')
from app.db import init_db, get_conn
init_db()
conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
print('tables:', [row[0] for row in cur.fetchall()])
