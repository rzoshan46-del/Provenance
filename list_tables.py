import os
import sqlite3
from app.db import init_db, get_db_path

# Ensure DB is initialized
init_db()

path = get_db_path()
conn = sqlite3.connect(str(path))
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
print('Tables:', [row[0] for row in cur.fetchall()])
