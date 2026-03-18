"""Temporary script — run once to verify all tables exist, then delete."""
from database import get_db

conn = get_db()
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print("Tables in catalog.db:")
for t in tables:
    print(" -", t[0])
conn.close()
